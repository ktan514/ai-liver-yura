from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.domain.activity_constraints import ValidatedConstraints


def _empty_mapping() -> Mapping[str, object]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class PluginCommand:
    command_type: str
    payload: Mapping[str, object] = field(default_factory=_empty_mapping)
    requires_confirmation: bool = False
    state_version: int | None = None
    validated_constraints: ValidatedConstraints | None = None


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


@dataclass(frozen=True, slots=True)
class PluginActivityRequest:
    plugin_id: str
    activity_kind: str
    priority: int
    context: Mapping[str, object]
    response_text: str
    memory_policy: MemoryPolicy = field(default_factory=MemoryPolicy)


@dataclass(frozen=True, slots=True)
class PluginExecutionResult:
    plugin_id: str
    handled: bool
    activity_request: PluginActivityRequest | None = None
    conversation_context: Mapping[str, object] = field(default_factory=_empty_mapping)
    reason: str = ""
    unavailable_capabilities: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class PromptFragment:
    source_plugin_id: str
    section_name: str
    content: str
    priority: int = 0
