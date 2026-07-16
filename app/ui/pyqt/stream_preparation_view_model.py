from __future__ import annotations

from dataclasses import dataclass

from app.domain.streaming import StreamPreparationResult


@dataclass(frozen=True, slots=True)
class StreamPreparationViewModel:
    status: str
    ready: bool
    failure_reason: str
    last_checked_at: str
    result: StreamPreparationResult

    @classmethod
    def from_result(cls, result: StreamPreparationResult) -> StreamPreparationViewModel:
        return cls(
            status=result.status,
            ready=result.ready,
            failure_reason="\n".join(result.failure_reasons),
            last_checked_at=result.completed_at.astimezone().isoformat(timespec="seconds"),
            result=result,
        )
