from __future__ import annotations

from typing import Protocol


class PolicyDecision(Protocol):
    @property
    def allowed(self) -> bool: ...

    @property
    def reason_code(self) -> str | None: ...


class ActivityPolicy(Protocol):
    def evaluate_policy(
        self,
        operation: str,
        context_id: str,
        *,
        activity_type: str | None = None,
        trace_id: str = "",
    ) -> PolicyDecision: ...
