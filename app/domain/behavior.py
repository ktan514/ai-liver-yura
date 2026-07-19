from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.domain.activities import ActivityResult
from app.domain.activity_constraints import (
    ConstraintValidationError,
    ValidatedConstraints,
)
from app.domain.trace_context import TraceContext
from app.shared.contracts.activity import (
    ActivityDefinition as ActivityDefinition,
)
from app.shared.contracts.activity import (
    ActivityMatcher as ActivityMatcher,
)
from app.shared.contracts.activity import (
    ActivityMatcherContext as ActivityMatcherContext,
)
from app.shared.contracts.activity import (
    ActivityOperation as ActivityOperation,
)
from app.shared.contracts.activity import (
    BehaviorDecision as BehaviorDecision,
)
from app.shared.contracts.activity import (
    DeterministicActivityMatch as DeterministicActivityMatch,
)
from app.shared.contracts.activity import (
    OngoingActivityPlanningContext as OngoingActivityPlanningContext,
)
from app.shared.contracts.activity import (
    OngoingInputDecision as OngoingInputDecision,
)
from app.shared.contracts.activity import (
    SpeechAct as SpeechAct,
)


@dataclass(frozen=True, slots=True)
class OngoingInputInterpretation:
    decision: OngoingInputDecision
    confidence: float
    reason: str
    current_activity_type: str
    requested_activity_type: str | None = None


@dataclass(frozen=True, slots=True)
class SituationAnalysis:
    """外部Eventの客観的な意味構造。実行可否や発話本文は含めない。"""

    activity_candidate: str | None
    operation: ActivityOperation | None
    goal: str
    constraints: dict[str, object] = field(default_factory=dict)
    speech_act: SpeechAct = SpeechAct.STATEMENT
    negated: bool = False
    hypothetical: bool = False
    past_reference: bool = False
    knowledge_question: bool = False
    confidence: float = 1.0
    reason: str = ""
    evaluator_type: str = "deterministic"
    ongoing_input_decision: OngoingInputDecision | None = None
    constraint_errors: tuple[ConstraintValidationError, ...] = ()
    constraints_schema_version: str | None = None
    matcher_id: str | None = None
    matcher_type: str | None = None
    matcher_evidence: str | None = None


@dataclass(frozen=True, slots=True)
class ActivityPlan:
    decision: BehaviorDecision
    activity_type: str
    goal: str
    required_capability: str | None = None
    provider_plugin_id: str | None = None
    operation: ActivityOperation | None = None
    constraints: dict[str, object] = field(default_factory=dict)
    planner_constraints: tuple[str, ...] = ()
    speech_act: SpeechAct = SpeechAct.STATEMENT
    negated: bool = False
    hypothetical: bool = False
    past_reference: bool = False
    knowledge_question: bool = False
    confidence: float = 1.0
    reason: str = ""
    planner_type: str = "deterministic"
    ongoing_input_decision: OngoingInputDecision | None = None
    current_activity_type: str | None = None
    current_activity_preserved: bool = False
    current_activity_paused: bool = False
    current_activity_stopped: bool = False
    requested_new_activity: str | None = None
    current_activity_capability: str | None = None
    current_activity_provider_plugin_id: str | None = None
    topic: str | None = None
    planning_reason: str | None = None
    autonomous_action: str | None = None
    constraint_errors: tuple[ConstraintValidationError, ...] = ()
    constraints_schema_version: str | None = None
    validated_constraints: ValidatedConstraints | None = None
    behavior_plan_id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: str | None = None
    parent_trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActivityPlanEvaluation:
    plan: ActivityPlan
    accepted: bool
    result: ActivityResult
    fallback_required: bool = False


@dataclass(frozen=True, slots=True)
class BehaviorPlanningContext:
    user_text: str
    source_event_id: str
    available_capabilities: frozenset[str]
    authority_role: str = "user"
    instruction_trusted: bool = False
    activity_definitions: tuple[ActivityDefinition, ...] = ()
    active_activity_definition: ActivityDefinition | None = None
    ongoing_activity_type: str | None = None
    ongoing_activity: OngoingActivityPlanningContext | None = None
    drive: dict[str, float] = field(default_factory=dict)
    emotion: dict[str, object] = field(default_factory=dict)
    relationship: dict[str, object] = field(default_factory=dict)
    situation: dict[str, object] = field(default_factory=dict)
    memory: dict[str, object] = field(default_factory=dict)
    last_activity_result: ActivityResult | None = None
    trace_context: TraceContext | None = None
