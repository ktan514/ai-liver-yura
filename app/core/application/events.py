"""Deprecated compatibility import. Use app.shared.observability."""

from app.shared.observability import (
    ApplicationEvent,
    ApplicationEventBroker,
    EventSubscription,
)

__all__ = ["ApplicationEvent", "ApplicationEventBroker", "EventSubscription"]
