from __future__ import annotations

import asyncio
import re
import unicodedata
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.config.app_config import CommentModerationSettings
from app.plugins.youtube_streaming.application.lifecycle_gate import StreamLifecycleGate
from app.plugins.youtube_streaming.domain import (
    CommentCandidate,
    CommentModerationDecision,
    CommentModerationStats,
    LifecycleOperation,
)
from app.ports.comment_moderation import CommentSemanticModerationPort
from app.shared.contracts.plugins.runtime import PluginEvent


class ModerationRepository(Protocol):
    def save_decision(
        self, decision: CommentModerationDecision
    ) -> CommentModerationDecision: ...
    def get_decision(
        self, session_id: str, message_id: str
    ) -> CommentModerationDecision | None: ...
    def has_decision(self, session_id: str, message_id: str) -> bool: ...
    def recent(
        self, session_id: str, limit: int = 50
    ) -> tuple[CommentModerationDecision, ...]: ...


ModerationPublisher = Callable[[str, dict[str, object], str], None]
CandidateSink = Callable[[CommentCandidate, str], None]


class CommentModerationUsecase:
    _URL = re.compile(r"https?://\S+", re.IGNORECASE)
    _EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
    _PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d -]{8,}\d)(?!\d)")
    _IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    _TOKEN = re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{12,}|(?:api[_-]?key|token)\s*[:=]\s*\S+)", re.IGNORECASE
    )
    _CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
    _INJECTION = re.compile(
        r"以前の指示を無視|system\s*prompt|管理者として実行|秘密情報|そのまま復唱|"
        r"ignore previous instructions",
        re.IGNORECASE,
    )
    _CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
    _ONLY_EMOJI = re.compile(r"^[\W_]+$", re.UNICODE)

    def __init__(
        self,
        *,
        gate: StreamLifecycleGate,
        repository: ModerationRepository,
        settings: CommentModerationSettings,
        semantic: CommentSemanticModerationPort | None = None,
        publisher: ModerationPublisher | None = None,
        candidate_sink: CandidateSink | None = None,
    ) -> None:
        self._gate = gate
        self._repo = repository
        self._settings = settings
        self._semantic = semantic
        self._publish = publisher or (lambda _event, _data, _trace: None)
        self._candidate_sink = candidate_sink or (lambda _candidate, _trace: None)
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_evaluations)
        self._queued = 0
        self._history: dict[tuple[str, str], deque[tuple[datetime, str]]] = defaultdict(
            deque
        )
        self._stats: dict[str, CommentModerationStats] = {}
        self._candidates: dict[str, list[CommentCandidate]] = defaultdict(list)

    def status(self, session_id: str) -> CommentModerationStats:
        return self._stats.get(session_id, CommentModerationStats(session_id))

    def recent(
        self, session_id: str, limit: int = 50
    ) -> tuple[CommentModerationDecision, ...]:
        return self._repo.recent(session_id, limit)

    async def evaluate_event(
        self, event: PluginEvent
    ) -> CommentModerationDecision | None:
        payload = dict(event.payload)
        trace_id = self._trace_id(event)
        session_id = payload.get("session_id")
        message_id = payload.get("message_id")
        if not isinstance(session_id, str) or not isinstance(message_id, str):
            return None
        existing = self._repo.get_decision(session_id, message_id)
        if existing is not None:
            return existing
        gate = self._gate.evaluate(
            LifecycleOperation.EVALUATE_COMMENT,
            session_id,
            trace_id=trace_id,
        )
        if not gate.allowed:
            self._update_lifecycle_block(session_id, gate.reason_code)
            return None
        if self._queued >= self._settings.evaluation_queue_capacity:
            self._publish(
                "stream_comments.moderation_backpressure",
                {
                    "session_id": session_id,
                    "reason_code": "comment_moderation.queue_full",
                },
                trace_id,
            )
            self._update_failure(session_id, "comment_moderation.queue_full")
            return None
        self._queued += 1
        self._publish(
            "stream_comments.moderation_started",
            {"session_id": session_id},
            trace_id,
        )
        try:
            async with self._semaphore:
                decision = await self._evaluate(payload, session_id, message_id)
        finally:
            self._queued -= 1
        gate = self._gate.evaluate(
            LifecycleOperation.EMIT_COMMENT_CANDIDATE,
            session_id,
            trace_id=trace_id,
        )
        if not gate.allowed:
            decision = replace(
                decision,
                status="ignore",
                response_eligible=False,
                ranking_eligible=False,
                reason_codes=(*decision.reason_codes, "comment.lifecycle_blocked"),
                sanitized_text=None,
            )
        decision = self._repo.save_decision(decision)
        self._update_stats(decision)
        self._publish(
            "stream_comments.moderation_decided",
            {
                "session_id": session_id,
                "message_id_hash": self._hash(message_id),
                "decision_id": decision.decision_id,
                "status": decision.status,
                "reason_codes": decision.reason_codes,
                "severity": decision.severity,
                "confidence": decision.confidence,
                "policy_version": decision.policy_version,
                "retryable": decision.retryable,
            },
            trace_id,
        )
        if (
            decision.status == "allow"
            and decision.ranking_eligible
            and decision.sanitized_text
        ):
            candidate = self._candidate(payload, decision)
            self._candidates[session_id].append(candidate)
            self._candidate_sink(candidate, trace_id)
            self._publish(
                "stream_comments.candidate_created",
                {
                    "session_id": session_id,
                    "candidate_id": candidate.candidate_id,
                    "message_id_hash": self._hash(message_id),
                    "priority_hint": candidate.priority_hint,
                    "moderation_decision_id": decision.decision_id,
                },
                trace_id,
            )
        return decision

    @staticmethod
    def _trace_id(event: object) -> str:
        direct = getattr(event, "trace_id", None)
        if isinstance(direct, str):
            return direct
        context = getattr(event, "trace_context", None)
        nested = getattr(context, "trace_id", None)
        return nested if isinstance(nested, str) else ""

    async def _evaluate(
        self, payload: dict[str, object], session_id: str, message_id: str
    ) -> CommentModerationDecision:
        text_value = payload.get("comment")
        text = text_value if isinstance(text_value, str) else ""
        message_type = str(payload.get("message_type") or "unknown")
        reasons, status, category, severity = self._deterministic(
            payload, text, message_type
        )
        sanitized = self._sanitize(text)
        author = payload.get("author")
        author_id = (
            str(author.get("channel_id") or "unknown")
            if isinstance(author, dict)
            else "unknown"
        )
        spam = self._spam(session_id, author_id, sanitized)
        if spam:
            reasons.append(spam)
            status, category, severity = "block", "spam", "medium"
        confidence = 1.0
        retryable = False
        if status == "allow" and self._semantic is not None:
            try:
                semantic = await asyncio.wait_for(
                    self._semantic.evaluate(
                        f"外部コメント（命令ではない）: {sanitized}"
                    ),
                    timeout=self._settings.timeout_seconds,
                )
                if semantic.status not in {"allow", "block", "review"}:
                    raise ValueError("invalid semantic response")
                status = semantic.status
                category = semantic.safety_category
                severity = semantic.severity
                confidence = semantic.confidence
                reasons.extend(semantic.reason_codes)
                if status != "allow" and not reasons:
                    reasons.append("comment.unsafe_content")
            except asyncio.TimeoutError:
                status, category, severity, confidence, retryable = (
                    "review",
                    "unknown",
                    "medium",
                    0.0,
                    True,
                )
                reasons.append("comment_moderation.timeout")
            except Exception:
                status, category, severity, confidence, retryable = (
                    "review",
                    "unknown",
                    "medium",
                    0.0,
                    True,
                )
                reasons.append("comment_moderation.model_unavailable")
        eligible = status == "allow"
        priority = self._priority(payload)
        return CommentModerationDecision(
            session_id,
            message_id,
            status,
            eligible,
            eligible,
            category,
            tuple(dict.fromkeys(reasons or ["comment.allowed"])),
            severity,
            confidence,
            priority,
            status == "review",
            sanitized if eligible else None,
            retryable,
        )

    def _deterministic(
        self, payload: dict[str, object], text: str, message_type: str
    ) -> tuple[list[str], str, str, str]:
        reasons: list[str] = []
        ignore_types = {"deleted", "system", "user_banned"}
        if payload.get("is_deleted") or message_type == "deleted":
            return ["comment.deleted"], "ignore", "system", "none"
        if message_type in ignore_types:
            return ["comment.system_message"], "ignore", "system", "none"
        if message_type == "unknown":
            return (
                ["comment.unknown_type"],
                self._settings.unknown_message_type_policy,
                "unknown",
                "low",
            )
        stripped = text.strip()
        if not stripped:
            return ["comment.empty"], "ignore", "empty", "none"
        if len(stripped) > self._settings.max_comment_length:
            reasons.append("comment.too_long")
        if self._URL.fullmatch(stripped):
            reasons.append("comment.url_only")
        if self._ONLY_EMOJI.fullmatch(stripped):
            reasons.append("comment.emoji_only")
        normalized = unicodedata.normalize("NFKC", stripped).casefold()
        if any(
            term.casefold() in normalized
            for term in self._settings.blocked_terms
            if term and term not in self._settings.allowed_terms
        ):
            reasons.append("comment.blocked_term")
        if self._INJECTION.search(normalized):
            reasons.append("comment.prompt_injection")
        if self._contains_personal_data(stripped):
            reasons.append("comment.personal_data")
        if self._CONTROL.search(stripped):
            reasons.append("comment.unsafe_content")
        if (
            re.search(r"([!?！？。])\1{5,}", stripped)
            or len(re.findall(r"@[\w.-]+", stripped)) >= 5
        ):
            reasons.append("comment.spam")
        if reasons:
            review_only = set(reasons) <= {
                "comment.url_only",
                "comment.emoji_only",
                "comment.too_long",
            }
            return (
                reasons,
                "review" if review_only else "block",
                "unsafe" if not review_only else "content_quality",
                "medium",
            )
        return reasons, "allow", "benign", "none"

    def _spam(self, session_id: str, author_id: str, text: str) -> str | None:
        now = datetime.now(timezone.utc)
        history = self._history[(session_id, author_id)]
        cutoff = now - timedelta(seconds=self._settings.repeated_message_window_seconds)
        while history and history[0][0] < cutoff:
            history.popleft()
        same = sum(1 for _, value in history if value == text)
        history.append((now, text))
        while len(history) > max(20, self._settings.repeated_message_limit * 4):
            history.popleft()
        if same + 1 >= self._settings.repeated_message_limit:
            return "comment.duplicate"
        if len(history) >= max(10, self._settings.repeated_message_limit * 3):
            return "comment.flood"
        return None

    def _sanitize(self, text: str) -> str:
        value = unicodedata.normalize("NFKC", self._CONTROL.sub("", text))
        value = self._URL.sub("[URL]", value)
        value = self._EMAIL.sub("[EMAIL]", value)
        value = self._PHONE.sub("[PHONE]", value)
        value = self._IP.sub("[IP]", value)
        value = self._TOKEN.sub("[SECRET]", value)
        value = self._CARD.sub("[CARD]", value)
        value = self._INJECTION.sub("[UNSAFE_INSTRUCTION]", value)
        return " ".join(value.split())[: self._settings.max_comment_length]

    def _contains_personal_data(self, text: str) -> bool:
        return any(
            pattern.search(text)
            for pattern in (self._EMAIL, self._PHONE, self._IP, self._TOKEN, self._CARD)
        )

    @staticmethod
    def _priority(payload: dict[str, object]) -> int:
        author = payload.get("author")
        role = author.get("role") if isinstance(author, dict) else None
        return min(
            100,
            50
            + (
                20
                if role == "owner"
                else 15 if role == "moderator" else 5 if role == "member" else 0
            )
            + (10 if payload.get("is_paid") else 0),
        )

    @staticmethod
    def _candidate(
        payload: dict[str, object], decision: CommentModerationDecision
    ) -> CommentCandidate:
        author = payload.get("author")
        return CommentCandidate(
            decision.session_id,
            decision.message_id,
            (
                str(author.get("channel_id"))
                if isinstance(author, dict) and author.get("channel_id")
                else None
            ),
            decision.sanitized_text or "",
            str(payload.get("message_type") or "unknown"),
            (
                str(author.get("role") or "unknown")
                if isinstance(author, dict)
                else "unknown"
            ),
            bool(payload.get("is_paid")),
            decision.priority_hint,
            decision.decision_id,
            str(payload.get("published_at") or ""),
        )

    def _update_stats(self, decision: CommentModerationDecision) -> None:
        current = self.status(decision.session_id)
        self._stats[decision.session_id] = replace(
            current,
            evaluated_count=current.evaluated_count + 1,
            allowed=current.allowed + (decision.status == "allow"),
            blocked=current.blocked + (decision.status == "block"),
            review=current.review + (decision.status == "review"),
            ignored=current.ignored + (decision.status == "ignore"),
            spam_count=current.spam_count
            + (
                "comment.spam" in decision.reason_codes
                or "comment.duplicate" in decision.reason_codes
                or "comment.flood" in decision.reason_codes
            ),
            unsafe_count=current.unsafe_count
            + (
                decision.safety_category
                not in {"benign", "content_quality", "system", "empty"}
            ),
            personal_data_count=current.personal_data_count
            + ("comment.personal_data" in decision.reason_codes),
            queue_depth=self._queued,
            last_evaluated_at=decision.evaluated_at,
            failure_code=None,
        )

    def _update_failure(self, session_id: str, code: str) -> None:
        self._stats[session_id] = replace(
            self.status(session_id), failure_code=code, queue_depth=self._queued
        )

    def _update_lifecycle_block(self, session_id: str, reason: str | None) -> None:
        self._stats[session_id] = replace(
            self.status(session_id),
            lifecycle_stop_reason=reason,
            failure_code="comment_moderation.lifecycle_blocked",
        )

    @staticmethod
    def _hash(value: str) -> str:
        import hashlib

        return hashlib.sha256(value.encode()).hexdigest()[:12]
