from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.core.contracts.plugins.protocols import (
    ActivityProvider,
    CommandHandler,
    PluginDescriptor,
    PluginEventSubscriber,
    PluginLifecycle,
    QueryHandler,
)


class PluginHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class PluginHealth:
    status: PluginHealthStatus
    details: Mapping[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CapabilityPolicy(str, Enum):
    SINGLE = "single"
    PRIORITY = "priority"
    NAMED_PROVIDER = "named_provider"
    EXPLICIT_SELECTION = "explicit_selection"


@dataclass(frozen=True, slots=True)
class CapabilityRegistration:
    capability: str
    policy: CapabilityPolicy = CapabilityPolicy.SINGLE
    priority: int = 0


@dataclass(frozen=True, slots=True)
class PluginActivityRequest:
    capability: str
    payload: Mapping[str, Any]
    trace_id: str


@dataclass(frozen=True, slots=True)
class EventSubscription:
    event_type: str
    handler: CommandHandler[Any, Any]


@dataclass(frozen=True, slots=True)
class PluginRegistration:
    descriptor: PluginDescriptor
    lifecycle: PluginLifecycle
    capability_registrations: tuple[CapabilityRegistration, ...]
    commands: Mapping[str, CommandHandler[Any, Any]] = field(default_factory=dict)
    queries: Mapping[str, QueryHandler[Any, Any]] = field(default_factory=dict)
    activity_providers: Mapping[str, ActivityProvider] = field(default_factory=dict)
    event_subscribers: tuple[PluginEventSubscriber, ...] = ()
    enabled: bool = True

