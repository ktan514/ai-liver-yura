from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.adapters.streaming import (
    InMemoryCommentCandidateRepository,
    InMemoryCommentRankingRepository,
    InMemoryCommentResponseHistoryRepository,
    InMemoryCommentSelectionRepository,
)
from app.plugins.youtube_streaming.domain import (
    CommentCandidate,
    CommentRankingFeature,
    CommentResponseTarget,
    RankedCommentCandidate,
)
from app.ports.comment_ranking import (
    CommentCandidateRepository,
    CommentRankingRepository,
    CommentResponseHistoryRepository,
    CommentSelectionRepository,
)


def candidate(session_id: str, candidate_id: str) -> CommentCandidate:
    return CommentCandidate(
        session_id,
        f"message-{candidate_id}",
        "author",
        f"text-{candidate_id}",
        "text",
        "viewer",
        False,
        50,
        f"decision-{candidate_id}",
        datetime.now(timezone.utc).isoformat(),
        candidate_id=candidate_id,
    )


def target(session_id: str, candidate_id: str = "candidate") -> CommentResponseTarget:
    now = datetime.now(timezone.utc)
    return CommentResponseTarget(
        session_id,
        candidate_id,
        f"message-{candidate_id}",
        "author",
        "safe text",
        0.8,
        1,
        "top",
        selection_id=f"selection-{candidate_id}",
        selected_at=now,
        expires_at=now + timedelta(seconds=30),
    )


def ranked(candidate_id: str, score: float, rank: int) -> RankedCommentCandidate:
    features = CommentRankingFeature(candidate_id, 1, 1, 1, 1, 1, 1, 1, 0)
    return RankedCommentCandidate(candidate_id, score, features, rank, True, ())


def test_candidate_repository_session_ttl_bound_duplicate_and_state() -> None:
    repository: CommentCandidateRepository = InMemoryCommentCandidateRepository(2)
    first = candidate("session-a", "first")
    repository.add(first)
    repository.add(first)
    assert repository.valid(
        "session-a", datetime.now(timezone.utc) - timedelta(seconds=1)
    ) == (first,)
    repository.add(candidate("session-b", "second"))
    assert (
        len(
            repository.valid(
                "session-b", datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
        == 1
    )
    repository.add(candidate("session-a", "third"))
    assert repository.dropped_count == 1
    repository.mark("session-a", "third", "selected")
    assert (
        repository.valid("session-a", datetime.now(timezone.utc) - timedelta(seconds=1))
        == ()
    )
    expired = candidate("session-a", "expired")
    repository.add(expired)
    assert (
        repository.valid("session-a", datetime.now(timezone.utc) + timedelta(seconds=1))
        == ()
    )
    assert repository.expired_count == 1


def test_ranking_repository_preserves_order_features_and_sessions() -> None:
    repository: CommentRankingRepository = InMemoryCommentRankingRepository()
    values = (ranked("top", 0.9, 1), ranked("next", 0.8, 2))
    repository.save("session-a", values)
    repository.save("session-b", (ranked("other", 0.7, 1),))
    assert repository.latest("session-a") == values
    assert repository.latest("session-a")[0].feature_scores.relevance_score == 1
    assert repository.latest("session-b")[0].candidate_id == "other"


def test_selection_repository_reserve_transitions_expiry_and_session_invalidation() -> (
    None
):
    repository: CommentSelectionRepository = InMemoryCommentSelectionRepository()
    item = target("session-a")
    assert repository.reserve(item)
    assert not repository.reserve(item)
    assert repository.current("session-a") == item
    consumed = repository.transition(item.selection_id, "consumed")
    assert consumed is not None and consumed.reservation_status == "consumed"
    assert repository.transition(item.selection_id, "released") is None

    released_item = target("session-a", "released")
    assert repository.reserve(released_item)
    assert repository.transition(released_item.selection_id, "released") is not None
    reacquired = repository.reserve_released(
        released_item.selection_id, datetime.now(timezone.utc) + timedelta(seconds=30)
    )
    assert reacquired is not None and reacquired.reservation_status == "reserved"

    expired = target("session-b", "expired")
    expired = CommentResponseTarget(
        expired.session_id,
        expired.candidate_id,
        expired.message_id,
        expired.author_id,
        expired.sanitized_text,
        expired.selected_score,
        expired.selected_rank,
        expired.selection_reason,
        selection_id=expired.selection_id,
        selected_at=expired.selected_at,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert repository.reserve(expired)
    assert repository.current("session-b") is None
    stored = repository.get(expired.selection_id)
    assert stored is not None and stored.reservation_status == "expired"

    active = target("session-c", "active")
    assert repository.reserve(active)
    repository.invalidate_session("session-c")
    assert repository.current("session-c") is None


def test_history_repository_is_bounded_and_session_separated() -> None:
    repository: CommentResponseHistoryRepository = (
        InMemoryCommentResponseHistoryRepository(2)
    )
    repository.record("session-a", "author-1", "topic-1", "text")
    repository.record("session-a", "author-2", "topic-2", "paid")
    repository.record("session-a", "author-3", "topic-3", "text")
    repository.record("session-b", "author-b", "topic-b", "text")
    assert repository.recent("session-a") == (
        ("author-2", "topic-2", "paid"),
        ("author-3", "topic-3", "text"),
    )
    assert repository.recent("session-b") == (("author-b", "topic-b", "text"),)


def test_usecase_and_port_modules_do_not_import_adapters() -> None:
    root = Path(__file__).parents[1]
    paths = (
        root / "app/plugins/youtube_streaming/application/comment_ranking.py",
        root / "app/ports/comment_ranking.py",
        root / "app/ports/comment_response.py",
    )
    for path in paths:
        tree = ast.parse(path.read_text())
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(name.startswith("app.adapters") for name in imported), path
