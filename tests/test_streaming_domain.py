from __future__ import annotations

import pytest

from app.adapters.streaming import InMemoryStreamSessionRepository
from app.domain.streaming import (
    HealthCheckItem,
    HealthStatus,
    ReadinessPolicy,
    StreamSession,
    StreamSessionStatus,
)


def test_stream_session_transitions_increment_version_and_control_start() -> None:
    session = StreamSession("trace", "broadcast", "title")
    assert session.status == StreamSessionStatus.CREATED
    assert session.state_version == 0
    preparing = session.transition(StreamSessionStatus.PREPARING)
    ready = preparing.transition(StreamSessionStatus.READY)
    assert ready.state_version == 2
    assert ready.can_start is True


def test_stream_session_supports_failed_retry_and_rejects_invalid_transition() -> None:
    session = StreamSession("trace", "broadcast", "title")
    failed = session.transition(StreamSessionStatus.PREPARING).transition(
        StreamSessionStatus.FAILED
    )
    assert failed.can_start is False
    assert failed.transition(StreamSessionStatus.PREPARING).state_version == 3
    with pytest.raises(ValueError):
        session.transition(StreamSessionStatus.READY)


def test_repository_prevents_multiple_active_sessions() -> None:
    repository = InMemoryStreamSessionRepository()
    repository.create(StreamSession("trace-1", "broadcast-1", "one"))
    with pytest.raises(ValueError):
        repository.create(StreamSession("trace-2", "broadcast-2", "two"))


def test_readiness_ignores_optional_unavailable_but_rejects_required() -> None:
    optional = HealthCheckItem("avatar", "avatar", HealthStatus.UNAVAILABLE, False, "unavailable")
    required = HealthCheckItem(
        "youtube",
        "youtube",
        HealthStatus.UNAVAILABLE,
        True,
        "unavailable",
        failure_reason="api down",
    )
    assert ReadinessPolicy().evaluate((optional,)).ready is True
    decision = ReadinessPolicy().evaluate((optional, required))
    assert decision.ready is False
    assert decision.failure_reasons == ("api down",)
