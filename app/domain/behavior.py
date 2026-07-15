from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from app.domain.activities import ActivityResult
from app.domain.activity_constraints import (
    ConstraintValidationError,
    ValidatedConstraints,
)


class BehaviorDecision(str, Enum):
    START_ACTIVITY = "start_activity"
    CONTINUE_ACTIVITY = "continue_activity"
    CONVERSATION = "conversation"
    ASK_CONFIRMATION = "ask_confirmation"
    WAIT = "wait"
    NO_ACTION = "no_action"
    SWITCH_ACTIVITY = "switch_activity"


class ActivityOperation(str, Enum):
    START = "start"
    CONTINUE = "continue"
    STOP = "stop"
    EXPLAIN = "explain"
    DISCUSS = "discuss"


class SpeechAct(str, Enum):
    STATEMENT = "statement"
    QUESTION = "question"
    REQUEST = "request"
    PROPOSAL = "proposal"
    COMMAND = "command"


class OngoingInputDecision(str, Enum):
    CONTINUE_CURRENT = "continue_current"
    STOP_CURRENT = "stop_current"
    PAUSE_CURRENT = "pause_current"
    RESUME_CURRENT = "resume_current"
    CONVERSATION_ABOUT_CURRENT = "conversation_about_current"
    CONVERSATION_UNRELATED = "conversation_unrelated"
    START_OTHER_ACTIVITY = "start_other_activity"
    SWITCH_ACTIVITY = "switch_activity"
    ASK_CONFIRMATION = "ask_confirmation"
    NO_ACTION = "no_action"


@dataclass(frozen=True, slots=True)
class OngoingActivityPlanningContext:
    ongoing_activity_id: str
    activity_type: str
    status: str
    goal: str
    constraints: dict[str, object]
    expected_input: str
    turn_count: int
    current_operation: str | None = None
    plugin_state_summary: dict[str, object] = field(default_factory=dict)
    recent_turns: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class OngoingInputInterpretation:
    decision: OngoingInputDecision
    confidence: float
    reason: str
    current_activity_type: str
    requested_activity_type: str | None = None


@dataclass(frozen=True, slots=True)
class DeterministicActivityMatch:
    operation: ActivityOperation
    goal: str
    constraints: dict[str, object] = field(default_factory=dict)
    confidence: float = 1.0
    reason: str = "deterministic_match"
    activity_type: str | None = None
    evidence: str | None = None
    matcher_id: str = "anonymous_matcher"
    matcher_type: str = "plugin"
    priority: int = 300


@dataclass(frozen=True, slots=True)
class ActivityMatcherContext:
    user_input: str
    normalized_input: str
    activity_definition: ActivityDefinition
    registered_activity_definitions: tuple[ActivityDefinition, ...]
    ongoing_activity: OngoingActivityPlanningContext | None = None
    conversation_context: dict[str, object] = field(default_factory=dict)


class ActivityMatcher(Protocol):
    """Activity固有の高精度判定をPlugin側へ閉じ込める。"""

    def match(self, context: ActivityMatcherContext) -> DeterministicActivityMatch | None: ...


@dataclass(frozen=True, slots=True)
class ActivityDefinition:
    """Pluginが提供可能なActivityの宣言。

    `start_markers` / `stop_markers` は旧Plugin読込専用のdeprecated入力であり、
    新規実装では`matchers`を使用する。全legacy利用がなくなった時点で削除する。
    """

    activity_type: str
    display_name: str
    required_capability: str
    provider_plugin_id: str
    start_markers: tuple[str, ...] = ()
    stop_markers: tuple[str, ...] = ()
    description: str = ""
    supported_operations: tuple[ActivityOperation, ...] = (ActivityOperation.START,)
    semantic_descriptions: tuple[str, ...] = ()
    constraints_schema: dict[str, object] = field(default_factory=dict)
    constraints_schema_version: str = "1"
    # Deprecated compatibility input. 新規Pluginでは使用禁止。
    matcher: ActivityMatcher | None = None
    matchers: tuple[ActivityMatcher, ...] = ()


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
    activity_definitions: tuple[ActivityDefinition, ...] = ()
    active_activity_definition: ActivityDefinition | None = None
    ongoing_activity_type: str | None = None
    ongoing_activity: OngoingActivityPlanningContext | None = None
    drive: dict[str, float] = field(default_factory=dict)
    emotion: dict[str, object] = field(default_factory=dict)
    last_activity_result: ActivityResult | None = None
