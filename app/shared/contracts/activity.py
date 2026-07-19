from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


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
    def match(
        self, context: ActivityMatcherContext
    ) -> DeterministicActivityMatch | None: ...


@dataclass(frozen=True, slots=True)
class ActivityDefinition:
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
    matcher: ActivityMatcher | None = None
    matchers: tuple[ActivityMatcher, ...] = ()


class ActivityPlanView(Protocol):
    @property
    def decision(self) -> BehaviorDecision: ...

    @property
    def activity_type(self) -> str: ...

    @property
    def operation(self) -> ActivityOperation | None: ...

    @property
    def constraints(self) -> dict[str, object]: ...

    @property
    def validated_constraints(self) -> Mapping[str, object] | None: ...

    @property
    def confidence(self) -> float: ...

    @property
    def required_capability(self) -> str | None: ...

    @property
    def provider_plugin_id(self) -> str | None: ...

    @property
    def reason(self) -> str: ...
