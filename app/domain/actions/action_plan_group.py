

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.domain.actions.action_plan import ActionPlan


@dataclass(frozen=True, slots=True)
class ActionPlanGroup:
    action_plans: list[ActionPlan] = field(default_factory=list)
    source_activity_id: str | None = None
    group_id: str = field(default_factory=lambda: str(uuid4()))

    def is_empty(self) -> bool:
        return not self.action_plans