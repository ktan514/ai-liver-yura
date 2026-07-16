from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HealthCheckItem:
    check_id: str
    component: str
    status: HealthStatus
    required: bool
    summary: str
    failure_reason: str | None = None
    observed_at: datetime = field(default_factory=utc_now)
    latency_ms: float = 0.0
    retryable: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StreamPreparationResult:
    session_id: str
    trace_id: str
    status: str
    ready: bool
    checks: tuple[HealthCheckItem, ...]
    failure_reasons: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    duplicate: bool = False
    version_mismatch: bool = False
    canceled: bool = False
