from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.domain.actions.action_resource import ActionResource
from app.domain.actions.action_type import ActionType


@dataclass(frozen=True, slots=True)
class ActionPlan:
    """Action 実行計画。

    Action は「今この瞬間に何をするか」を表す。
    Activity が目的、ActionPlan が実行単位。
    """

    action_type: ActionType
    text: str = ""
    required_resources: set[ActionResource] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_activity_id: str | None = None
    output_unit_id: str | None = None
    action_id: str = field(default_factory=lambda: str(uuid4()))
