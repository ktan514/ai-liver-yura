from __future__ import annotations

from dataclasses import dataclass

from app.plugins.youtube_streaming.domain.health import HealthCheckItem, HealthStatus


@dataclass(frozen=True, slots=True)
class ReadinessDecision:
    ready: bool
    failure_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    """必須Checkだけを開始可否へ反映する準備段階のPolicy。"""

    allow_required_degraded: bool = False

    def evaluate(self, checks: tuple[HealthCheckItem, ...]) -> ReadinessDecision:
        failures: list[str] = []
        for item in checks:
            if not item.required:
                continue
            accepted = item.status == HealthStatus.HEALTHY or (
                self.allow_required_degraded and item.status == HealthStatus.DEGRADED
            )
            if not accepted:
                failures.append(
                    item.failure_reason or f"{item.check_id}: {item.status.value}"
                )
        return ReadinessDecision(ready=not failures, failure_reasons=tuple(failures))
