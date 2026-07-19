from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from uuid import uuid4


def _empty_mapping() -> Mapping[str, object]:
    return MappingProxyType({})


SPEAK_ACTION_TYPE = "speak"


@dataclass(frozen=True, slots=True)
class PluginCommand:
    command_type: str
    operation: str | None = None
    payload: Mapping[str, object] = field(default_factory=_empty_mapping)
    requires_confirmation: bool = False
    state_version: int | None = None
    validated_constraints: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class PluginIntentResult:
    plugin_id: str
    handled: bool
    confidence: float
    command: PluginCommand | None = None
    reason: str = ""
    classifier_type: str = "deterministic"
    conversation_context: Mapping[str, object] = field(default_factory=_empty_mapping)


@dataclass(frozen=True, slots=True)
class MemoryPolicy:
    skip_topic_memory: bool = False
    skip_embedding: bool = False
    skip_long_term_summary: bool = False


class PluginActivityStatus(str, Enum):
    WAITING_INPUT = "waiting_input"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    CANCELED = "canceled"


@dataclass(frozen=True, slots=True)
class PluginActivityState:
    """CoreがPlugin固有Sessionの内部型を知らずに継続状態を同期する契約。"""

    session_id: str
    status: PluginActivityStatus
    expected_input: str
    end_condition: str


@dataclass(frozen=True, slots=True)
class PluginActivityRequest:
    plugin_id: str
    activity_kind: str
    priority: int
    context: Mapping[str, object]
    response_text: str
    state: PluginActivityState
    memory_policy: MemoryPolicy = field(default_factory=MemoryPolicy)


@dataclass(frozen=True, slots=True)
class PluginActivityWorkItem:
    """Plugin内部の生成処理をCore Activity型から分離する一時作業DTO。"""

    goal: str
    priority: int
    context: Mapping[str, object]
    interruptible: bool = False
    work_item_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True, slots=True)
class PluginActionResult:
    action_id: str
    action_type: str
    status: str


@dataclass(frozen=True, slots=True)
class PluginCharacterResult:
    result_id: str
    adopted_text: str | None = None


@dataclass(frozen=True, slots=True)
class PluginOutputResult:
    action_results: tuple[PluginActionResult, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginActivityResult:
    """Pluginへ公開する、Core内部集約に依存しないActivity実行結果。"""

    activity_turn_id: str
    final_status: str
    failure_stage: str | None = None
    character_result: PluginCharacterResult | None = None
    output_result: PluginOutputResult | None = None


@dataclass(frozen=True, slots=True)
class PluginEvent:
    """PluginとCoreの境界を流れる汎用Event DTO。"""

    event_type: str
    payload: Mapping[str, object] = field(default_factory=_empty_mapping)
    priority: int = 0
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: str(uuid4()))
    discardable: bool = False
    replace_key: str | None = None
    trace_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True, slots=True)
class PluginExecutionResult:
    plugin_id: str
    handled: bool
    activity_request: PluginActivityRequest | None = None
    conversation_context: Mapping[str, object] = field(default_factory=_empty_mapping)
    reason: str = ""
    unavailable_capabilities: frozenset[str] = field(default_factory=frozenset)
    activity_state: PluginActivityState | None = None


@dataclass(frozen=True, slots=True)
class PromptFragment:
    source_plugin_id: str
    section_name: str
    content: str
    priority: int = 0
