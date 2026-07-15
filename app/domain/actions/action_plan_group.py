from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.domain.actions.action_plan import ActionPlan
from app.domain.activity_turn_result import ActivityTurnResult


@dataclass(frozen=True, slots=True)
class ActionPlanGroup:
    action_plans: list[ActionPlan] = field(default_factory=list)
    source_activity_id: str | None = None
    output_priority: int = 0
    group_id: str = field(default_factory=lambda: str(uuid4()))
    activity_turn_result: ActivityTurnResult | None = None

    def is_empty(self) -> bool:
        return not self.action_plans
