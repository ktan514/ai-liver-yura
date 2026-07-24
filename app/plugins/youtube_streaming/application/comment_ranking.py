from __future__ import annotations

import asyncio
import math
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.config.app_config import CommentRankingSettings
from app.plugins.youtube_streaming.application.lifecycle_gate import StreamLifecycleGate
from app.plugins.youtube_streaming.domain import (
    CommentCandidate,
    CommentRankingContext,
    CommentRankingFeature,
    CommentRankingStats,
    CommentResponseTarget,
    LifecycleOperation,
    RankedCommentCandidate,
)
from app.ports.comment_ranking import (
    CommentCandidateRepository,
    CommentRankingRepository,
    CommentResponseHistoryRepository,
    CommentSelectionRepository,
    CommentSemanticRankingPort,
)

RankingPublisher = Callable[[str, dict[str, object], str], None]


class CommentRankingUsecase:
    def __init__(
        self,
        *,
        gate: StreamLifecycleGate,
        candidates: CommentCandidateRepository,
        rankings: CommentRankingRepository,
        selections: CommentSelectionRepository,
        history: CommentResponseHistoryRepository,
        settings: CommentRankingSettings,
        semantic: CommentSemanticRankingPort | None = None,
        publisher: RankingPublisher | None = None,
    ) -> None:
        self._gate = gate
        self._candidates = candidates
        self._rankings = rankings
        self._selections = selections
        self._history = history
        self._settings = settings
        self._semantic = semantic
        self._publish = publisher or (lambda _event, _data, _trace: None)
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_rankings)
        self._queued = 0
        self._stats: dict[str, CommentRankingStats] = {}
        self._selection_locks: dict[str, asyncio.Lock] = {}

    def add_candidate(self, candidate: CommentCandidate) -> None:
        self._candidates.add(candidate)

    def status(self, session_id: str) -> CommentRankingStats:
        current = self._stats.get(session_id, CommentRankingStats(session_id))
        valid = self._valid_candidates(session_id)
        return replace(
            current,
            pool_size=len(valid),
            expired_count=self._candidates.expired_count,
            dropped_count=self._candidates.dropped_count,
        )

    def top(
        self, session_id: str, limit: int = 10
    ) -> tuple[RankedCommentCandidate, ...]:
        return self._rankings.latest(session_id)[: max(0, min(limit, 20))]

    def current_selection(self, session_id: str) -> CommentResponseTarget | None:
        return self._selections.current(session_id)

    def selection(self, selection_id: str) -> CommentResponseTarget | None:
        return self._selections.get(selection_id)

    def reacquire(self, selection_id: str) -> CommentResponseTarget | None:
        return self._selections.reserve_released(
            selection_id,
            datetime.now(timezone.utc)
            + timedelta(seconds=self._settings.reservation_ttl_seconds),
        )

    async def add_and_select(
        self, candidate: CommentCandidate, context: CommentRankingContext, trace_id: str
    ) -> CommentResponseTarget | None:
        self.add_candidate(candidate)
        return await self.select(candidate.session_id, context, trace_id)

    async def select(
        self, session_id: str, context: CommentRankingContext, trace_id: str = ""
    ) -> CommentResponseTarget | None:
        lock = self._selection_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            return await self._select(session_id, context, trace_id)

    async def _select(
        self, session_id: str, context: CommentRankingContext, trace_id: str
    ) -> CommentResponseTarget | None:
        started = time.perf_counter()
        if self._queued >= self._settings.queue_capacity:
            return self._not_selected(
                session_id, ("comment_ranking.queue_full",), 0, trace_id
            )
        gate = self._gate.evaluate(
            LifecycleOperation.SELECT_COMMENT_RESPONSE_TARGET,
            session_id,
            trace_id=trace_id,
        )
        if not gate.allowed:
            self._stats[session_id] = replace(
                self.status(session_id),
                failure_code="comment_ranking.lifecycle_blocked",
                lifecycle_stop_reason=gate.reason_code,
            )
            return self._not_selected(
                session_id,
                (gate.reason_code or "comment_ranking.lifecycle_blocked",),
                0,
                trace_id,
            )
        if not context.speech_idle or not context.activity_interruptible:
            return self._not_selected(
                session_id, ("comment_ranking.activity_busy",), 0, trace_id
            )
        if self.current_selection(session_id) is not None:
            return self._not_selected(
                session_id, ("comment_ranking.reservation_exists",), 0, trace_id
            )
        pool = self._valid_candidates(session_id)[: self._settings.max_rank_batch_size]
        if not pool:
            return self._not_selected(
                session_id, ("comment_ranking.no_candidate",), 0, trace_id
            )
        self._queued += 1
        run_id = str(uuid4())
        self._publish(
            "stream_comments.ranking_started",
            {
                "session_id": session_id,
                "ranking_run_id": run_id,
                "candidate_count": len(pool),
            },
            trace_id,
        )
        try:
            async with self._semaphore:
                ranked = await self._rank(session_id, pool, context)
        finally:
            self._queued -= 1
        gate = self._gate.evaluate(
            LifecycleOperation.SELECT_COMMENT_RESPONSE_TARGET,
            session_id,
            trace_id=trace_id,
        )
        if not gate.allowed:
            return self._not_selected(
                session_id, ("comment_ranking.stale_result",), len(pool), trace_id
            )
        self._rankings.save(session_id, ranked)
        for item in ranked:
            self._candidates.mark(session_id, item.candidate_id, "ranked")
        duration = round((time.perf_counter() - started) * 1000, 3)
        self._stats[session_id] = replace(
            self.status(session_id),
            ranked_count=self.status(session_id).ranked_count + len(ranked),
            last_ranking_at=datetime.now(timezone.utc),
            failure_code=None,
        )
        self._publish(
            "stream_comments.ranking_completed",
            {
                "session_id": session_id,
                "ranking_run_id": run_id,
                "ranked_count": len(ranked),
                "top": [self._rank_summary(item) for item in ranked[:3]],
                "evaluation_duration_ms": duration,
            },
            trace_id,
        )
        selected = next((item for item in ranked if item.eligible), None)
        if selected is None:
            reasons = tuple(
                dict.fromkeys(
                    reason for item in ranked for reason in item.exclusion_reasons
                )
            ) or ("comment_ranking.below_threshold",)
            return self._not_selected(session_id, reasons, len(pool), trace_id)
        candidate = next(
            item for item in pool if item.candidate_id == selected.candidate_id
        )
        now = datetime.now(timezone.utc)
        target = CommentResponseTarget(
            session_id=session_id,
            candidate_id=candidate.candidate_id,
            message_id=candidate.message_id,
            author_id=candidate.author_id,
            sanitized_text=candidate.sanitized_text,
            selected_score=selected.total_score,
            selected_rank=selected.rank,
            selection_reason="highest_eligible_score",
            selected_at=now,
            expires_at=now + timedelta(seconds=self._settings.reservation_ttl_seconds),
        )
        if not self._selections.reserve(target):
            return self._not_selected(
                session_id,
                ("comment_ranking.duplicate_reservation",),
                len(pool),
                trace_id,
            )
        gate = self._gate.evaluate(
            LifecycleOperation.SELECT_COMMENT_RESPONSE_TARGET,
            session_id,
            trace_id=trace_id,
        )
        if not gate.allowed:
            self._selections.transition(target.selection_id, "released")
            return self._not_selected(
                session_id, ("comment_ranking.stale_result",), len(pool), trace_id
            )
        self._candidates.mark(session_id, candidate.candidate_id, "selected")
        self._history.record(
            session_id,
            candidate.author_id,
            candidate.sanitized_text,
            candidate.message_type,
        )
        self._stats[session_id] = replace(
            self.status(session_id),
            selected_count=self.status(session_id).selected_count + 1,
        )
        self._publish(
            "stream_comments.target_selected",
            {
                "session_id": session_id,
                "selection_id": target.selection_id,
                "candidate_id": target.candidate_id,
                "selected_score": target.selected_score,
                "selected_rank": target.selected_rank,
                "selection_reason": target.selection_reason,
                "expires_at": target.expires_at.isoformat(),
            },
            trace_id,
        )
        return target

    def release(self, selection_id: str) -> CommentResponseTarget | None:
        return self._selections.transition(selection_id, "released")

    def consume(self, selection_id: str) -> CommentResponseTarget | None:
        return self._selections.transition(selection_id, "consumed")

    def invalidate_session(self, session_id: str) -> None:
        self._selections.invalidate_session(session_id)

    async def _rank(
        self,
        session_id: str,
        pool: tuple[CommentCandidate, ...],
        context: CommentRankingContext,
    ) -> tuple[RankedCommentCandidate, ...]:
        values: list[tuple[CommentCandidate, CommentRankingFeature, bool]] = []
        history = self._history.recent(session_id)
        for candidate in pool:
            feature, fallback = await self._features(candidate, context, history)
            values.append((candidate, feature, fallback))
        raw = [
            (candidate, feature, fallback, self._aggregate(feature))
            for candidate, feature, fallback in values
        ]
        raw.sort(key=lambda item: (-item[3], item[0].eligible_at, item[0].candidate_id))
        result = []
        seen_text: set[str] = set()
        for rank, (candidate, feature, fallback, score) in enumerate(raw, 1):
            exclusions = []
            normalized = self._normalize(candidate.sanitized_text)
            if normalized in seen_text:
                exclusions.append("comment_ranking.duplicate_text")
            seen_text.add(normalized)
            if feature.conversation_fit_score < self._settings.minimum_conversation_fit:
                exclusions.append("comment_ranking.no_conversation_fit")
            if score < self._settings.selection_threshold:
                exclusions.append("comment_ranking.below_threshold")
            if history and candidate.author_id == history[-1][0]:
                exclusions.append("comment_ranking.author_cooldown")
            result.append(
                RankedCommentCandidate(
                    candidate.candidate_id,
                    score,
                    feature,
                    rank,
                    not exclusions,
                    tuple(exclusions),
                    fallback,
                )
            )
        return tuple(result)

    async def _features(
        self,
        candidate: CommentCandidate,
        context: CommentRankingContext,
        history: tuple[tuple[str | None, str, str], ...],
    ) -> tuple[CommentRankingFeature, bool]:
        age = max(
            0.0, (datetime.now(timezone.utc) - candidate.eligible_at).total_seconds()
        )
        recency = max(
            0.1, math.exp(-age / max(1, self._settings.candidate_ttl_seconds))
        )
        text_tokens = self._tokens(candidate.sanitized_text)
        context_tokens = self._tokens(
            f"{context.current_topic} {context.recent_agent_utterance}"
        )
        relevance = (
            self._overlap(text_tokens, context_tokens) if context_tokens else 0.55
        )
        engagement = min(
            1.0,
            0.35
            + (0.3 if re.search(r"[?？]", candidate.sanitized_text) else 0.0)
            + (0.2 if len(text_tokens) >= 3 else 0.0)
            + (
                0.15
                if any(
                    mark in candidate.sanitized_text
                    for mark in ("楽しい", "好き", "どう", "なぜ")
                )
                else 0.0
            ),
        )
        recent_texts = [self._normalize(item[1]) for item in history]
        novelty = (
            0.2 if self._normalize(candidate.sanitized_text) in recent_texts else 0.9
        )
        same_author = sum(
            1
            for item in history[-self._settings.author_cooldown_count :]
            if item[0] == candidate.author_id
        )
        fairness = max(0.0, 1.0 - same_author * 0.6)
        same_type = sum(1 for item in history[-5:] if item[2] == candidate.message_type)
        diversity = max(0.2, 1.0 - same_type * 0.15)
        fit = (
            0.9
            if context.speech_idle
            and context.activity_interruptible
            and context.current_segment == "main"
            else 0.2
        )
        fallback = False
        if self._semantic is not None:
            try:
                semantic = await asyncio.wait_for(
                    self._semantic.score(
                        candidate.sanitized_text,
                        context.current_topic,
                        context.recent_agent_utterance,
                    ),
                    timeout=self._settings.semantic_timeout_seconds,
                )
                scores = (
                    semantic.relevance,
                    semantic.conversation_fit,
                    semantic.novelty,
                )
                if any(
                    not math.isfinite(score) or score < 0 or score > 1
                    for score in scores
                ):
                    raise ValueError("invalid semantic score")
                relevance = min(relevance, semantic.relevance)
                fit = min(fit, semantic.conversation_fit)
                novelty = min(novelty, semantic.novelty)
            except Exception:
                fallback = True
                relevance = min(relevance, 0.5)
                fit = min(fit, 0.6)
                novelty = min(novelty, 0.6)
        priority = min(0.1, max(0.0, (candidate.priority_hint - 50) / 300))
        return (
            CommentRankingFeature(
                candidate.candidate_id,
                self._score(recency),
                self._score(relevance),
                self._score(novelty),
                self._score(fit),
                self._score(engagement),
                self._score(fairness),
                self._score(diversity),
                priority,
                repetition_penalty=0.2 if novelty < 0.5 else 0.0,
                interruption_penalty=0.5 if not context.speech_idle else 0.0,
            ),
            fallback,
        )

    def _aggregate(self, feature: CommentRankingFeature) -> float:
        weights = self._settings.weights
        value = (
            weights["recency"] * feature.recency_score
            + weights["relevance"] * feature.relevance_score
            + weights["novelty"] * feature.novelty_score
            + weights["conversation_fit"] * feature.conversation_fit_score
            + weights["engagement"] * feature.engagement_score
            + weights["fairness"] * feature.author_fairness_score
            + feature.priority_adjustment
            - feature.repetition_penalty
            - feature.interruption_penalty
        )
        return self._score(value)

    def _valid_candidates(self, session_id: str) -> tuple[CommentCandidate, ...]:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self._settings.candidate_ttl_seconds
        )
        return self._candidates.valid(session_id, cutoff)

    def _not_selected(
        self, session_id: str, reasons: tuple[str, ...], count: int, trace_id: str
    ) -> CommentResponseTarget | None:
        self._publish(
            "stream_comments.target_not_selected",
            {
                "session_id": session_id,
                "reason_codes": reasons,
                "candidate_count": count,
            },
            trace_id,
        )
        result: CommentResponseTarget | None = None
        return result

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(
            re.findall(
                r"[\wぁ-んァ-ヶ一-龠]{2,}",
                unicodedata.normalize("NFKC", text).casefold(),
            )
        )

    @staticmethod
    def _normalize(text: str) -> str:
        return "".join(CommentRankingUsecase._tokens(text))

    @staticmethod
    def _overlap(left: set[str], right: set[str]) -> float:
        return len(left & right) / max(1, len(left | right))

    @staticmethod
    def _score(value: float) -> float:
        return round(min(1.0, max(0.0, value)), 6)

    @staticmethod
    def _rank_summary(item: RankedCommentCandidate) -> dict[str, object]:
        return {
            "candidate_id": item.candidate_id,
            "rank": item.rank,
            "total_score": item.total_score,
            "eligible": item.eligible,
            "exclusion_reasons": item.exclusion_reasons,
            "fallback_used": item.fallback_used,
            "policy_version": item.policy_version,
        }
