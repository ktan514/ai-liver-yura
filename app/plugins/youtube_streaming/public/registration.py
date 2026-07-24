from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.plugins.youtube_streaming.application.service import (
    StreamingApplicationService,
)
from app.plugins.youtube_streaming.public.activity_provider import (
    StreamingActivityProvider,
)
from app.shared.contracts.plugins.registration import (
    CapabilityRegistration,
    CommandRejected,
    PluginHealth,
    PluginHealthStatus,
    PluginRegistration,
)


class MethodHandler:
    def __init__(self, callback: Callable[[Any], Any]) -> None:
        self._callback = callback

    async def handle(self, value: Any) -> Any:
        try:
            result = self._callback(value)
            return await result if inspect.isawaitable(result) else result
        except CommandRejected:
            raise
        except Exception as error:
            raise CommandRejected(
                "YouTube Streaming command/query rejected",
                plugin_id="youtube_streaming",
                reason_code=str(
                    getattr(error, "code", None) or error or "stream.operation_failed"
                ),
            ) from error


@dataclass(frozen=True, slots=True)
class YouTubeStreamingDescriptor:
    capabilities: frozenset[str]
    plugin_id: str = "youtube_streaming"
    version: str = "1.0.0"
    dependencies: tuple[str, ...] = ()


class YouTubeStreamingLifecycle:
    def __init__(self, service: StreamingApplicationService) -> None:
        self._service = service
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        poller = self._service._comment_poller  # noqa: SLF001 - same plugin boundary
        if poller is not None:
            poller.stop("plugin.stopping")
        await self._service.runtime.obs_control.disconnect()
        self._started = False

    async def health(self) -> PluginHealth:
        return PluginHealth(
            PluginHealthStatus.HEALTHY if self._started else PluginHealthStatus.STOPPED,
            {"manual_check_log": self._service.manual_check_status()},
        )


def _commands(service: StreamingApplicationService) -> dict[str, MethodHandler]:
    values: dict[str, Callable[[Any], Any]] = {
        "manual_check.ui.record": service.record_ui_operation,
        "youtube.auth.start": lambda value: service.start_authentication(
            str(value["command_id"])
        ),
        "stream.broadcast.refresh": lambda _: service.broadcasts(),
        "obs.status.refresh": lambda _: service.refresh_obs(),
        "stream.session.prepare": service.prepare,
        "stream.session.approve_start": service.approve_start,
        "stream.opening.retry": service.retry_opening,
        "stream.main.retry": service.retry_main_segment,
        "stream.end.normal": service.approve_end,
        "stream.end.emergency": service.emergency_stop,
        "stream.comment.response.retry": service.retry_comment_response,
        "stream.comment.status.refresh": lambda _: service.refresh_comments_status(),
    }
    if service.demo_mode:
        values["demo.live_chat.submit"] = service.enqueue_demo_comment
    return {
        capability: MethodHandler(callback) for capability, callback in values.items()
    }


def _queries(service: StreamingApplicationService) -> dict[str, MethodHandler]:
    values: Mapping[str, Callable[[], Any]] = {
        "youtube.auth.status": service.auth_status,
        "stream.broadcast.list": service.broadcasts,
        "stream.run_of_show.list": service.run_of_shows,
        "stream.session.status.get": service.current_session,
        "stream.capability.status": service.capabilities,
        "obs.status.get": service.refresh_obs,
        "stream.start.status.get": service.start_status,
        "stream.opening.status.get": service.opening_status,
        "stream.main.status.get": service.main_segment_status,
        "stream.end.status.get": service.end_status,
        "stream.lifecycle.status.get": service.lifecycle_status,
        "stream.comment_pipeline.status.get": service.comments_status,
        "stream.moderation.status.get": service.moderation_status,
        "stream.moderation.recent.list": service.moderation_recent,
        "stream.ranking.status.get": service.ranking_status,
        "stream.ranking.top.list": service.ranking_top,
        "stream.selection.current.get": service.current_comment_selection,
        "stream.comment.response.status.get": service.comment_response_status,
        "stream.comment.response.recent.list": service.comment_response_recent,
    }
    handlers: dict[str, MethodHandler] = {}
    for capability, callback in values.items():

        def invoke(_: Any, selected: Callable[[], Any] = callback) -> Any:
            return selected()

        handlers[capability] = MethodHandler(invoke)
    return handlers


def create_registration(
    service: StreamingApplicationService, *, enabled: bool = True
) -> PluginRegistration:
    commands = _commands(service)
    queries = _queries(service)
    activity_capabilities = frozenset(
        {
            "stream.activity.opening",
            "stream.activity.main",
            "stream.activity.comment_response",
            "stream.activity.closing",
        }
    )
    activity_provider = StreamingActivityProvider()
    activity_providers = {
        capability: activity_provider for capability in activity_capabilities
    }
    capabilities = frozenset(commands) | frozenset(queries) | activity_capabilities
    return PluginRegistration(
        descriptor=YouTubeStreamingDescriptor(capabilities),
        lifecycle=YouTubeStreamingLifecycle(service),
        capability_registrations=tuple(
            CapabilityRegistration(capability) for capability in sorted(capabilities)
        ),
        commands=commands,
        queries=queries,
        activity_providers=activity_providers,
        enabled=enabled,
    )
