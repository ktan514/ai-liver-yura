from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, cast

from app.adapters.streaming import (
    InMemoryCommentCandidateRepository,
    InMemoryCommentModerationRepository,
    InMemoryCommentRankingRepository,
    InMemoryCommentResponseActivityRepository,
    InMemoryCommentResponseHistory,
    InMemoryCommentResponseHistoryRepository,
    InMemoryCommentSelectionRepository,
)
from app.admin_api.service import AdminApiService
from app.core.application.events import ApplicationEventBroker
from app.core.application.plugins import ActivityDispatcher, PluginRegistry
from app.core.contracts.plugins import PluginActivityRequest
from app.domain.events import AgentEvent, AgentEventType
from app.plugins.youtube_streaming.application.service import StreamingApplicationService
from app.plugins.youtube_streaming.public.activity_provider import StreamingActivityProvider
from app.plugins.youtube_streaming.public.evidence import ManualCheckRecorder
from app.plugins.youtube_streaming.public.registration import create_registration
from app.runtime.runtime_coordinator import RuntimeCoordinator


class RuntimeCoreActivityAdapter:
    """Only the composition root knows both Plugin capabilities and Core runtime."""

    def __init__(self, runtime: RuntimeCoordinator) -> None:
        self._runtime = runtime
        self._activities: ActivityDispatcher | None = None
        self._fallback_activity_provider = StreamingActivityProvider()

    def bind_registry(self, registry: PluginRegistry) -> None:
        self._activities = ActivityDispatcher(registry)

    async def execute(
        self, capability: str, payload: dict[str, object], trace_id: str
    ) -> Any:
        request = PluginActivityRequest(capability, payload, trace_id)
        activity = (
            await self._activities.dispatch(request)
            if self._activities is not None
            else await self._fallback_activity_provider.create_activity(request)
        )
        return await self._runtime.execute_external_activity(activity)

    async def publish_event(self, event: AgentEvent) -> None:
        await self._runtime.publish_event(event)

    def configure_lifecycle_gate(self, gate: Any) -> None:
        self._runtime.configure_activity_policy(gate)

        def enrich(event: AgentEvent) -> AgentEvent:
            if event.event_type not in {
                AgentEventType.YOUTUBE_COMMENT,
                AgentEventType.CURIOSITY_PEAK,
            } or isinstance(event.payload.get("session_id"), str):
                return event
            session_id = gate.active_session_id()
            return (
                replace(event, payload={**event.payload, "session_id": session_id})
                if session_id is not None
                else event
            )

        self._runtime.register_event_enricher(enrich)

    def configure_comment_moderation(self, handler: Any) -> None:
        self._runtime.subscribe_event(
            AgentEventType.YOUTUBE_COMMENT,
            handler,
            predicate=lambda event: event.payload.get("moderation_status") == "not_evaluated",
        )

    def cancel_outputs(self) -> bool:
        return self._runtime.cancel_outputs()


class DefaultStreamingRepositoryFactory:
    def moderation(self) -> Any:
        return InMemoryCommentModerationRepository()

    def candidates(self, max_pool_size: int) -> Any:
        return InMemoryCommentCandidateRepository(max_pool_size)

    def rankings(self) -> Any:
        return InMemoryCommentRankingRepository()

    def selections(self) -> Any:
        return InMemoryCommentSelectionRepository()

    def response_activities(self) -> Any:
        return InMemoryCommentResponseActivityRepository()

    def response_history(self) -> Any:
        return InMemoryCommentResponseHistory()

    def ranking_history(self, history_size: int) -> Any:
        return InMemoryCommentResponseHistoryRepository(history_size)


@dataclass(frozen=True, slots=True)
class StreamingComposition:
    application: StreamingApplicationService
    admin_api: AdminApiService
    registry: PluginRegistry
    broker: ApplicationEventBroker


def compose_streaming(
    runtime_components: Any,
    *,
    runtime: RuntimeCoordinator | None = None,
    demo_mode: bool = False,
    manual_check_log: object | None = None,
    enabled: bool = True,
) -> StreamingComposition:
    broker = ApplicationEventBroker()
    application = StreamingApplicationService(
        runtime_components,
        broker,
        demo_mode=demo_mode,
        manual_check_log=cast(ManualCheckRecorder | None, manual_check_log),
        repository_factory=DefaultStreamingRepositoryFactory(),
    )
    activity_adapter = RuntimeCoreActivityAdapter(runtime) if runtime is not None else None
    if activity_adapter is not None:
        application.configure_opening(activity_adapter)
    registry = PluginRegistry()
    registry.register(create_registration(application, enabled=enabled))
    if activity_adapter is not None:
        activity_adapter.bind_registry(registry)
    return StreamingComposition(
        application=application,
        admin_api=AdminApiService(
            registry,
            broker,
            runtime_status=lambda: {
                "runtime_mode": "streaming_demo" if demo_mode else "standard",
                "manual_check_log": application.manual_check_status(),
                "config_path": runtime_components.config.config_path,
                "adapter_modes": {
                    "youtube": runtime_components.usecase.youtube_adapter_type,
                    "obs": runtime_components.usecase.obs_adapter_type,
                },
                "obs_connection": {
                    "host": runtime_components.config.services["obs"].host,
                    "port": runtime_components.config.services["obs"].port,
                    "password_env_set": bool(
                        runtime_components.config.services["obs"].password_env
                        and os.getenv(
                            runtime_components.config.services["obs"].password_env or ""
                        )
                    ),
                },
            },
        ),
        registry=registry,
        broker=broker,
    )
