from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.adapters.streaming import (
    InMemoryCommentCandidateRepository,
    InMemoryCommentRankingRepository,
    InMemoryCommentResponseHistoryRepository,
    InMemoryCommentSelectionRepository,
    InMemoryStreamMainSegmentRepository,
    InMemoryStreamOpeningRepository,
)
from app.adapters.streaming.in_memory_session_repository import (
    InMemoryStreamSessionRepository,
)
from app.config.app_config import CommentRankingSettings
from app.plugins.youtube_streaming.application import (
    CommentRankingUsecase,
    StreamLifecycleGate,
)
from app.plugins.youtube_streaming.domain import (
    CommentCandidate,
    CommentRankingContext,
    StreamMainSegmentActivity,
    StreamMainSegmentStatus,
    StreamSession,
    StreamSessionStatus,
)
from app.ports.comment_ranking import SemanticRankingScores

ACTIVE = {
    "obs_output": "active",
    "youtube_stream": "active",
    "youtube_broadcast": "live",
    "stream_session": "live",
}


class Semantic:
    def __init__(
        self,
        scores: SemanticRankingScores | None = None,
        error: Exception | None = None,
    ):
        self.scores = scores or SemanticRankingScores(0.8, 0.8, 0.8)
        self.error = error

    async def score(
        self, sanitized_text: str, topic: str, recent_utterance: str
    ) -> SemanticRankingScores:
        assert sanitized_text
        if self.error:
            raise self.error
        return self.scores


def setup(
    settings: CommentRankingSettings | None = None, semantic: Semantic | None = None
) -> tuple[CommentRankingUsecase, str, list[tuple[str, dict[str, object]]]]:
    sessions = InMemoryStreamSessionRepository()
    session = sessions.create(
        StreamSession("trace", "broadcast", "title", status=StreamSessionStatus.LIVE)
    )
    main = InMemoryStreamMainSegmentRepository()
    main.create(
        StreamMainSegmentActivity(
            session.session_id,
            "trace",
            "main",
            1,
            topic="ゲーム",
            status=StreamMainSegmentStatus.COMPLETED,
        )
    )
    gate = StreamLifecycleGate(
        sessions=sessions,
        openings=InMemoryStreamOpeningRepository(),
        main_segments=main,
    )
    gate.update_external_state(session.session_id, ACTIVE)
    config = settings or CommentRankingSettings(selection_threshold=0.45)
    events: list[tuple[str, dict[str, object]]] = []
    usecase = CommentRankingUsecase(
        gate=gate,
        candidates=InMemoryCommentCandidateRepository(config.max_pool_size),
        rankings=InMemoryCommentRankingRepository(),
        selections=InMemoryCommentSelectionRepository(),
        history=InMemoryCommentResponseHistoryRepository(config.history_size),
        settings=config,
        semantic=semantic,
        publisher=lambda name, data, _trace: events.append((name, data)),
    )
    return usecase, session.session_id, events


def candidate(
    session_id: str,
    candidate_id: str,
    text: str,
    *,
    author: str = "viewer",
    priority: int = 50,
) -> CommentCandidate:
    return CommentCandidate(
        session_id,
        f"message-{candidate_id}",
        author,
        text,
        "text",
        "viewer",
        priority > 50,
        priority,
        f"decision-{candidate_id}",
        datetime.now(timezone.utc).isoformat(),
        candidate_id=candidate_id,
    )


@pytest.mark.asyncio
async def test_features_weighted_ranking_and_top_one_reservation() -> None:
    usecase, session_id, events = setup()
    usecase.add_candidate(candidate(session_id, "plain", "こんにちは"))
    usecase.add_candidate(
        candidate(session_id, "question", "ゲームはどうして好きですか？")
    )
    selected = await usecase.select(
        session_id,
        CommentRankingContext(
            current_topic="ゲーム", recent_agent_utterance="ゲームの話"
        ),
        "trace",
    )
    assert selected is not None and selected.candidate_id == "question"
    top = usecase.top(session_id)
    assert top[0].rank == 1
    assert 0 <= top[0].total_score <= 1
    assert (
        top[0].feature_scores.engagement_score > top[1].feature_scores.engagement_score
    )
    assert usecase.current_selection(session_id) == selected
    assert any(name == "stream_comments.target_selected" for name, _ in events)


@pytest.mark.asyncio
async def test_threshold_and_busy_are_normal_zero_selection() -> None:
    settings = CommentRankingSettings(selection_threshold=1.0)
    usecase, session_id, events = setup(settings)
    usecase.add_candidate(candidate(session_id, "one", "短文"))
    assert await usecase.select(session_id, CommentRankingContext()) is None
    assert (
        "comment_ranking.below_threshold"
        in usecase.top(session_id)[0].exclusion_reasons
    )
    usecase.add_candidate(candidate(session_id, "two", "質問ですか？"))
    assert (
        await usecase.select(session_id, CommentRankingContext(speech_idle=False))
        is None
    )
    assert any(name == "stream_comments.target_not_selected" for name, _ in events)


@pytest.mark.asyncio
async def test_semantic_invalid_or_unavailable_uses_conservative_fallback() -> None:
    usecase, session_id, _events = setup(semantic=Semantic(error=RuntimeError("down")))
    usecase.add_candidate(candidate(session_id, "one", "ゲームは楽しいですか？"))
    await usecase.select(session_id, CommentRankingContext(current_topic="ゲーム"))
    assert usecase.top(session_id)[0].fallback_used

    invalid, invalid_session, _ = setup(
        semantic=Semantic(SemanticRankingScores(2.0, 0.5, 0.5))
    )
    invalid.add_candidate(
        candidate(invalid_session, "invalid", "ゲームは楽しいですか？")
    )
    await invalid.select(invalid_session, CommentRankingContext(current_topic="ゲーム"))
    assert invalid.top(invalid_session)[0].fallback_used


@pytest.mark.asyncio
async def test_fairness_duplicate_reservation_release_consume_and_expiry() -> None:
    usecase, session_id, _events = setup()
    usecase.add_candidate(
        candidate(session_id, "first", "最初の質問ですか？", author="same")
    )
    first = await usecase.select(session_id, CommentRankingContext())
    assert first is not None
    assert await usecase.select(session_id, CommentRankingContext()) is None
    assert usecase.release(first.selection_id) is not None
    usecase.add_candidate(
        candidate(session_id, "second", "別の質問ですか？", author="same")
    )
    second = await usecase.select(session_id, CommentRankingContext())
    assert second is None

    other, other_session, _ = setup()
    other.add_candidate(
        candidate(other_session, "other", "新しい人の質問ですか？", author="new")
    )
    target = await other.select(other_session, CommentRankingContext())
    assert target is not None
    assert other.consume(target.selection_id) is not None


@pytest.mark.asyncio
async def test_expired_bounded_pool_and_stable_tie_order() -> None:
    settings = CommentRankingSettings(max_pool_size=2, selection_threshold=1.0)
    usecase, session_id, _events = setup(settings)
    expired = replace(
        candidate(session_id, "expired", "old"),
        eligible_at=datetime.now(timezone.utc) - timedelta(seconds=100),
    )
    usecase.add_candidate(expired)
    usecase.add_candidate(candidate(session_id, "b", "same"))
    usecase.add_candidate(candidate(session_id, "a", "same"))
    await usecase.select(session_id, CommentRankingContext())
    assert usecase.status(session_id).dropped_count == 1
    assert [item.candidate_id for item in usecase.top(session_id)] == ["b", "a"]
