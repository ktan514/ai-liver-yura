"""Prepare a YouTube streaming session and evaluate readiness."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TypeVar, cast

from app.plugins.youtube_streaming.domain import (
    HealthCheckItem,
    HealthStatus,
    ObsPreparationSnapshot,
    ReadinessPolicy,
    RunOfShowSummary,
    StreamPreparationCommand,
    StreamPreparationResult,
    StreamSession,
    StreamSessionStatus,
    YouTubeAuthenticationState,
    YouTubeAuthenticationStatus,
    YouTubeBroadcastStatus,
    YouTubeBroadcastSummary,
    YouTubeLiveChatSnapshot,
    YouTubeLiveChatStatus,
    YouTubeStreamSnapshot,
    YouTubeStreamStatus,
)
from app.plugins.youtube_streaming.domain.health import utc_now
from app.ports.streaming_preparation import (
    AvatarHealthPort,
    ObsPreparationPort,
    RunOfShowRepository,
    StreamPreparationPublisher,
    StreamSessionRepository,
    TtsHealthPort,
    YouTubePreparationPort,
)
from app.utils.trace import TraceLogger

T = TypeVar("T")
CapabilityReporter = Callable[[str, HealthStatus, str | None, datetime], None]


@dataclass(frozen=True, slots=True)
class StreamPreparationRequirements:
    require_youtube: bool = True
    require_obs: bool = True
    require_tts: bool = True
    require_avatar: bool = False
    require_run_of_show: bool = True
    require_emergency_stop: bool = False
    require_live_chat: bool = False
    expected_scene_collection: str = "AI Liver"
    expected_start_scene: str = "Starting Soon"
    required_audio_sources: tuple[str, ...] = ("VOICEVOX",)
    require_obs_avatar_visible: bool = False
    timeout_seconds: float = 5.0


class PrepareStreamSessionUsecase:
    def __init__(
        self,
        *,
        youtube: YouTubePreparationPort,
        obs: ObsPreparationPort,
        tts: TtsHealthPort,
        avatar: AvatarHealthPort,
        run_of_show: RunOfShowRepository,
        sessions: StreamSessionRepository,
        publisher: StreamPreparationPublisher,
        requirements: StreamPreparationRequirements,
        readiness_policy: ReadinessPolicy | None = None,
        capability_reporter: CapabilityReporter | None = None,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self._youtube = youtube
        self._obs = obs
        self._tts = tts
        self._avatar = avatar
        self._run_of_show = run_of_show
        self._sessions = sessions
        self._publisher = publisher
        self._requirements = requirements
        self._readiness_policy = readiness_policy or ReadinessPolicy()
        self._capability_reporter = capability_reporter
        self._trace = trace_logger or TraceLogger()
        self._command_results: dict[str, StreamPreparationResult] = {}
        self._lock = asyncio.Lock()

    def create_session(
        self,
        broadcast: YouTubeBroadcastSummary,
        *,
        trace_id: str,
        run_of_show_id: str = "default",
    ) -> StreamSession:
        return self._sessions.create(
            StreamSession(
                trace_id=trace_id,
                selected_broadcast_id=broadcast.broadcast_id,
                title=broadcast.title,
                run_of_show_id=run_of_show_id,
            )
        )

    async def list_broadcasts(self) -> tuple[YouTubeBroadcastSummary, ...]:
        return await self._youtube.list_broadcasts()

    @property
    def youtube_adapter_type(self) -> str:
        return self._youtube.adapter_type

    @property
    def obs_adapter_type(self) -> str:
        return self._obs.adapter_type

    async def get_youtube_authentication_state(self) -> YouTubeAuthenticationState:
        state = await self._youtube.get_authentication_state()
        self._report_authentication_state(state)
        return state

    async def authenticate_youtube(self) -> YouTubeAuthenticationState:
        state = await self._youtube.authenticate()
        self._report_authentication_state(state)
        return state

    def list_run_of_shows(self) -> tuple[RunOfShowSummary, ...]:
        return self._run_of_show.list_available()

    def get_session(self, session_id: str) -> StreamSession | None:
        return self._sessions.get(session_id)

    def find_active_session(self) -> StreamSession | None:
        return self._sessions.find_active_or_preparing()

    async def inspect_obs(self) -> tuple[HealthCheckItem, ...]:
        """Run only read-only OBS preparation checks without changing a session."""
        return await self._obs_checks()

    async def execute(
        self, command: StreamPreparationCommand
    ) -> StreamPreparationResult:
        async with self._lock:
            cached = self._command_results.get(command.command_id)
            if cached is not None:
                self._trace.info(
                    "stream_preparation:duplicate_command",
                    trace_id=command.trace_id,
                    session_id=command.session_id,
                    command_id=command.command_id,
                )
                return replace(cached, duplicate=True)
            result = await self._execute_once(command)
            self._command_results[command.command_id] = result
            return result

    async def _execute_once(
        self, command: StreamPreparationCommand
    ) -> StreamPreparationResult:
        started_at = utc_now()
        session = self._sessions.get(command.session_id)
        if session is None:
            return self._rejected_result(
                command, started_at, "未知のStreamSessionです。"
            )
        if session.state_version != command.expected_state_version:
            self._trace.warning(
                "stream_preparation:version_mismatch",
                trace_id=command.trace_id,
                session_id=session.session_id,
                command_id=command.command_id,
                expected_state_version=command.expected_state_version,
                actual_state_version=session.state_version,
            )
            return self._rejected_result(
                command,
                started_at,
                "StreamSessionのstate_versionが一致しません。",
                version_mismatch=True,
            )
        if session.selected_broadcast_id != command.selected_broadcast_id:
            return self._rejected_result(
                command, started_at, "選択したBroadcastが一致しません。"
            )

        session = self._sessions.save(
            session.transition(
                StreamSessionStatus.PREPARING,
                trace_id=command.trace_id,
                run_of_show_id=command.run_of_show_id,
                health_snapshot=(),
                failure_reasons=(),
            )
        )
        self._trace.info(
            "stream_preparation:started",
            trace_id=command.trace_id,
            source_event_id=command.command_id,
            session_id=session.session_id,
            command_id=command.command_id,
            status=session.status.value,
        )
        try:
            groups = await asyncio.gather(
                self._runtime_checks(),
                self._youtube_checks(command.selected_broadcast_id),
                self._obs_checks(),
                self._single_check(
                    "tts.available",
                    self._tts.check(required=self._requirements.require_tts),
                    self._requirements.require_tts,
                ),
                self._single_check(
                    "avatar.available",
                    self._avatar.check(required=self._requirements.require_avatar),
                    self._requirements.require_avatar,
                ),
                self._run_of_show_checks(command.run_of_show_id),
                self._emergency_stop_checks(),
            )
            checks = tuple(item for group in groups for item in group)
        except asyncio.CancelledError:
            result = self._cancel(command, session, started_at)
            self._command_results[command.command_id] = result
            return result

        decision = self._readiness_policy.evaluate(checks)
        for item in checks:
            self._trace.debug(
                "stream_preparation:health_check",
                trace_id=command.trace_id,
                source_event_id=command.command_id,
                session_id=session.session_id,
                command_id=command.command_id,
                health_check_id=item.check_id,
                component=item.component,
                status=item.status.value,
                required=item.required,
                failure_reason=item.failure_reason,
                observed_at=item.observed_at,
                latency_ms=item.latency_ms,
            )
            if item.required and item.status != HealthStatus.HEALTHY:
                self._trace.warning(
                    "stream_preparation:required_check_failed",
                    trace_id=command.trace_id,
                    session_id=session.session_id,
                    command_id=command.command_id,
                    health_check_id=item.check_id,
                    component=item.component,
                    status=item.status.value,
                    failure_reason=item.failure_reason,
                )
        stream_id = next(
            (
                str(item.metadata["stream_id"])
                for item in checks
                if item.check_id == "youtube.stream.bound"
                and "stream_id" in item.metadata
            ),
            None,
        )
        live_chat_id = next(
            (
                str(item.metadata["live_chat_id"])
                for item in checks
                if item.check_id == "youtube.live_chat.available"
                and item.metadata.get("live_chat_id")
            ),
            None,
        )
        status = (
            StreamSessionStatus.READY if decision.ready else StreamSessionStatus.FAILED
        )
        session = self._sessions.save(
            session.transition(
                status,
                selected_stream_id=stream_id,
                live_chat_id=live_chat_id,
                health_snapshot=checks,
                failure_reasons=decision.failure_reasons,
            )
        )
        result = StreamPreparationResult(
            session_id=session.session_id,
            trace_id=command.trace_id,
            status=session.status.value,
            ready=decision.ready,
            checks=checks,
            failure_reasons=decision.failure_reasons,
            started_at=started_at,
            completed_at=utc_now(),
        )
        self._publish_and_report(result)
        self._trace.info(
            "stream_preparation:completed",
            trace_id=command.trace_id,
            source_event_id=command.command_id,
            session_id=session.session_id,
            command_id=command.command_id,
            status=session.status.value,
            ready=result.ready,
            failure_reasons=result.failure_reasons,
        )
        return result

    async def _runtime_checks(self) -> tuple[HealthCheckItem, ...]:
        return (
            self._item(
                "runtime.running",
                "runtime",
                True,
                HealthStatus.HEALTHY,
                "Runtimeは稼働しています。",
            ),
        )

    async def _youtube_checks(self, broadcast_id: str) -> tuple[HealthCheckItem, ...]:
        required = self._requirements.require_youtube
        checks: list[HealthCheckItem] = []
        auth = await self._call(
            "youtube.authentication",
            "youtube",
            required,
            self._youtube.check_authentication(),
        )
        checks.append(
            self._boolean_item(
                auth, "YouTube認証を確認しました。", "YouTube認証に失敗しました。"
            )
        )
        api = await self._call(
            "youtube.api.available", "youtube", required, self._youtube.health_check()
        )
        checks.append(
            self._boolean_item(
                api, "YouTube APIを利用できます。", "YouTube APIを利用できません。"
            )
        )
        broadcast = await self._call(
            "youtube.broadcast.resolvable",
            "youtube",
            required,
            self._youtube.resolve_broadcast(broadcast_id),
        )
        broadcast_item = self._object_item(broadcast, "Broadcastを解決しました。")
        checks.append(broadcast_item)
        stream = await self._call(
            "youtube.stream.bound",
            "youtube",
            required,
            self._youtube.resolve_bound_stream(broadcast_id),
        )
        stream_item = self._object_item(stream, "YouTube Streamのbindを確認しました。")
        stream_value: YouTubeStreamSnapshot | None = None
        if stream.status == HealthStatus.HEALTHY and stream.value is not None:
            stream_value = cast(YouTubeStreamSnapshot, stream.value)
            stream_item = self._replace_metadata(
                stream_item,
                {
                    "stream_id": stream_value.stream_id,
                    "stream_status": stream_value.status,
                    "stream_health": stream_value.health_status,
                    "ingestion_type": stream_value.ingestion_type,
                },
            )
        checks.append(stream_item)

        broadcast_status = await self._call(
            "youtube.broadcast.status",
            "youtube",
            required,
            self._youtube.get_broadcast_status(broadcast_id),
        )
        broadcast_status_value = (
            str(broadcast_status.value)
            if broadcast_status.value is not None
            else "unknown"
        )
        invalid_broadcast = {
            YouTubeBroadcastStatus.COMPLETE.value,
            YouTubeBroadcastStatus.REVOKED.value,
            YouTubeBroadcastStatus.FAILED.value,
            YouTubeBroadcastStatus.UNKNOWN.value,
        }
        checks.append(
            self._from_call(
                broadcast_status,
                (
                    HealthStatus.UNAVAILABLE
                    if broadcast_status.status != HealthStatus.HEALTHY
                    or broadcast_status_value in invalid_broadcast
                    else HealthStatus.HEALTHY
                ),
                f"Broadcast状態: {broadcast_status_value}",
                broadcast_status.failure_reason
                or (
                    f"Broadcastは準備できない状態です: {broadcast_status_value}"
                    if broadcast_status_value in invalid_broadcast
                    else None
                ),
            )
        )

        if stream_value is None:
            stream_status = self._CallResult(
                "youtube.stream.status",
                "youtube",
                required,
                HealthStatus.UNAVAILABLE,
                0.0,
                failure_reason="bind済みStreamを解決できません。",
            )
        else:
            stream_status = await self._call(
                "youtube.stream.status",
                "youtube",
                required,
                self._youtube.get_stream_status(stream_value.stream_id),
            )
        stream_status_value = (
            str(stream_status.value) if stream_status.value is not None else "unknown"
        )
        expected_stream_status = (
            YouTubeStreamStatus.ACTIVE.value
            if broadcast_status_value == YouTubeBroadcastStatus.LIVE.value
            else YouTubeStreamStatus.READY.value
        )
        stream_status_ok = (
            stream_status.status == HealthStatus.HEALTHY
            and stream_status_value == expected_stream_status
        )
        checks.append(
            self._from_call(
                stream_status,
                HealthStatus.HEALTHY if stream_status_ok else HealthStatus.UNAVAILABLE,
                f"Stream状態: {stream_status_value}",
                stream_status.failure_reason
                or (
                    None
                    if stream_status_ok
                    else f"Stream状態は{expected_stream_status}である必要があります。"
                ),
            )
        )
        if stream_value is not None:
            health_ok = stream_value.health_status in {"healthy", "degraded"}
            checks.append(
                self._condition(
                    "youtube.stream.health",
                    "youtube",
                    required,
                    health_ok,
                    f"Stream health: {stream_value.health_status}",
                    f"Stream healthを確認できません: {stream_value.health_status}",
                )
            )

        chat = await self._call(
            "youtube.live_chat.available",
            "youtube",
            self._requirements.require_live_chat,
            self._youtube.get_live_chat_availability(broadcast_id),
        )
        chat_item = self._object_item(chat, "Live Chatを確認しました。")
        if chat.status == HealthStatus.HEALTHY and chat.value is not None:
            chat_value = cast(YouTubeLiveChatSnapshot, chat.value)
            available = chat_value.status == YouTubeLiveChatStatus.AVAILABLE
            chat_item = self._from_call(
                chat,
                (
                    HealthStatus.HEALTHY
                    if available
                    else (
                        HealthStatus.UNAVAILABLE
                        if self._requirements.require_live_chat
                        else HealthStatus.DEGRADED
                    )
                ),
                f"Live Chat: {chat_value.status.value}",
                None if available else chat_value.reason,
            )
            if chat_value.live_chat_id:
                chat_item = self._replace_metadata(
                    chat_item, {"live_chat_id": chat_value.live_chat_id}
                )
        checks.append(chat_item)
        return tuple(checks)

    async def _obs_checks(self) -> tuple[HealthCheckItem, ...]:
        required = self._requirements.require_obs
        snapshot = await self._call(
            "obs.connected", "obs", required, self._obs.snapshot()
        )
        if snapshot.status != HealthStatus.HEALTHY or snapshot.value is None:
            reason = snapshot.failure_reason or "OBS状態を取得できません。"
            return (
                self._item(
                    "obs.configuration",
                    "obs",
                    required,
                    HealthStatus.UNAVAILABLE,
                    "obs.configuration.invalid",
                    failure_reason=reason,
                ),
                self._object_item(snapshot, "OBSへ接続しました。"),
                self._item(
                    "obs.websocket.version",
                    "obs",
                    required,
                    HealthStatus.UNKNOWN,
                    "obs.websocket.version.unconfirmed",
                    failure_reason=reason,
                ),
                self._item(
                    "obs.idle",
                    "obs",
                    required,
                    HealthStatus.UNKNOWN,
                    "OBS出力状態は未確認です。",
                    failure_reason=reason,
                ),
                self._item(
                    "obs.scene_collection",
                    "obs",
                    required,
                    HealthStatus.UNKNOWN,
                    "Scene Collectionは未確認です。",
                    failure_reason=reason,
                ),
                self._item(
                    "obs.start_scene",
                    "obs",
                    required,
                    HealthStatus.UNKNOWN,
                    "開始Sceneは未確認です。",
                    failure_reason=reason,
                ),
                self._item(
                    "obs.audio_sources",
                    "obs",
                    required,
                    HealthStatus.UNKNOWN,
                    "音声Sourceは未確認です。",
                    failure_reason=reason,
                ),
                self._item(
                    "obs.avatar_source",
                    "obs",
                    self._requirements.require_avatar,
                    HealthStatus.UNKNOWN,
                    "Avatar Sourceは未確認です。",
                    failure_reason=reason,
                ),
            )
        value = cast(ObsPreparationSnapshot, snapshot.value)
        audio_details = value.audio_source_details
        missing = [
            name
            for name in self._requirements.required_audio_sources
            if not audio_details.get(name, {}).get(
                "exists", value.audio_source_states.get(name, False)
            )
        ]
        muted = [
            name
            for name, item in audio_details.items()
            if name in self._requirements.required_audio_sources
            and item.get("muted") is True
        ]
        low_volume = [
            name
            for name, item in audio_details.items()
            if name in self._requirements.required_audio_sources
            and item.get("low_volume") is True
        ]
        optional_audio_issues = [
            name
            for name, item in audio_details.items()
            if name not in self._requirements.required_audio_sources
            and (
                item.get("exists") is False
                or item.get("muted") is True
                or item.get("low_volume") is True
            )
        ]
        audio_ok = not missing and not muted
        audio_status = (
            HealthStatus.UNAVAILABLE
            if not audio_ok
            else HealthStatus.DEGRADED if low_volume else HealthStatus.HEALTHY
        )
        avatar_required = self._requirements.require_obs_avatar_visible
        avatar_ok = value.avatar_source_exists and value.avatar_source_visible
        avatar_status = (
            HealthStatus.HEALTHY
            if avatar_ok
            else HealthStatus.UNAVAILABLE if avatar_required else HealthStatus.DEGRADED
        )
        checks = (
            self._item(
                "obs.configuration",
                "obs",
                required,
                HealthStatus.HEALTHY,
                "obs.configuration.valid",
            ),
            self._item(
                "obs.connected",
                "obs",
                required,
                HealthStatus.HEALTHY if value.connected else HealthStatus.UNAVAILABLE,
                "obs.connected" if value.connected else "obs.disconnected",
                failure_reason=None if value.connected else "obs.connection_failed",
            ),
            self._item(
                "obs.websocket.version",
                "obs",
                required,
                (
                    HealthStatus.HEALTHY
                    if value.obs_version and value.websocket_version
                    else HealthStatus.UNAVAILABLE
                ),
                "obs.websocket.version.compatible",
                failure_reason=(
                    None
                    if value.obs_version and value.websocket_version
                    else "obs.protocol_version_unsupported"
                ),
            ),
            self._condition(
                "obs.idle",
                "obs",
                required,
                value.output_status == "idle",
                "obs.output.idle",
                f"obs.output.not_idle.{value.output_status}",
            ),
            self._condition(
                "obs.scene_collection",
                "obs",
                required,
                value.current_scene_collection
                == self._requirements.expected_scene_collection,
                "obs.scene_collection.matches",
                "obs.scene_collection.mismatch",
            ),
            self._condition(
                "obs.start_scene",
                "obs",
                required,
                value.current_scene == self._requirements.expected_start_scene,
                "obs.start_scene.matches",
                "obs.start_scene.mismatch",
            ),
            self._item(
                "obs.audio_sources",
                "obs",
                required,
                audio_status,
                (
                    "obs.audio_sources.ready"
                    if audio_ok
                    else "obs.audio_sources.unavailable"
                ),
                failure_reason=None if audio_ok else "obs.audio_sources.invalid",
            ),
            self._item(
                "obs.avatar_source",
                "obs",
                avatar_required,
                avatar_status,
                (
                    "obs.avatar_source.visible"
                    if avatar_ok
                    else "obs.avatar_source.hidden"
                ),
                failure_reason=None if avatar_ok else "obs.avatar_source.unavailable",
            ),
        )
        metadata = {
            "obs_version": value.obs_version or "unknown",
            "websocket_version": value.websocket_version or "unknown",
            "output_status": value.output_status,
            "current_scene_collection": value.current_scene_collection,
            "current_scene": value.current_scene,
            "missing_audio_sources": missing,
            "muted_audio_sources": muted,
            "low_volume_audio_sources": low_volume,
            "optional_audio_source_issues": optional_audio_issues,
            "avatar_visible": value.avatar_source_visible,
            "avatar_paths": list(value.avatar_source_paths),
            "adapter_type": value.adapter_type,
        }
        return tuple(self._replace_metadata(item, metadata) for item in checks)

    async def _run_of_show_checks(
        self, run_of_show_id: str
    ) -> tuple[HealthCheckItem, ...]:
        required = self._requirements.require_run_of_show
        result = await self._call(
            "run_of_show.loadable",
            "run_of_show",
            required,
            asyncio.to_thread(self._run_of_show.validate, run_of_show_id),
        )
        return (self._object_item(result, "RunOfShowを読み込みました。"),)

    async def _emergency_stop_checks(self) -> tuple[HealthCheckItem, ...]:
        required = self._requirements.require_emergency_stop
        return (
            self._item(
                "emergency_stop.available",
                "runtime",
                required,
                HealthStatus.DEGRADED,
                "緊急停止は今回の実装範囲外です。",
                failure_reason="緊急停止は未実装です。",
            ),
        )

    async def _single_check(
        self, check_id: str, awaitable: Awaitable[HealthCheckItem], required: bool
    ) -> tuple[HealthCheckItem, ...]:
        try:
            return (
                await asyncio.wait_for(awaitable, self._requirements.timeout_seconds),
            )
        except Exception as error:
            return (
                self._item(
                    check_id,
                    check_id.split(".")[0],
                    required,
                    HealthStatus.UNAVAILABLE,
                    "Health Checkに失敗しました。",
                    failure_reason=str(error),
                    retryable=True,
                ),
            )

    @dataclass(frozen=True, slots=True)
    class _CallResult:
        check_id: str
        component: str
        required: bool
        status: HealthStatus
        latency_ms: float
        value: object | None = None
        failure_reason: str | None = None

    async def _call(
        self, check_id: str, component: str, required: bool, awaitable: Awaitable[T]
    ) -> _CallResult:
        started = time.perf_counter()
        try:
            value = await asyncio.wait_for(
                awaitable, self._requirements.timeout_seconds
            )
            return self._CallResult(
                check_id,
                component,
                required,
                HealthStatus.HEALTHY,
                (time.perf_counter() - started) * 1000,
                value,
            )
        except asyncio.TimeoutError:
            return self._CallResult(
                check_id,
                component,
                required,
                HealthStatus.UNAVAILABLE,
                (time.perf_counter() - started) * 1000,
                failure_reason="Health Checkがtimeoutしました。",
            )
        except Exception as error:
            return self._CallResult(
                check_id,
                component,
                required,
                HealthStatus.UNAVAILABLE,
                (time.perf_counter() - started) * 1000,
                failure_reason=str(error),
            )

    def _boolean_item(self, result: _CallResult, ok: str, ng: str) -> HealthCheckItem:
        if result.status == HealthStatus.HEALTHY and result.value is False:
            return self._from_call(result, HealthStatus.UNAVAILABLE, ng, ng)
        return self._from_call(
            result,
            result.status,
            ok if result.status == HealthStatus.HEALTHY else ng,
            result.failure_reason,
        )

    def _object_item(
        self, result: _CallResult, ok: str, *, none_is_degraded: bool = False
    ) -> HealthCheckItem:
        if (
            result.status == HealthStatus.HEALTHY
            and result.value is None
            and none_is_degraded
        ):
            return self._from_call(
                result,
                HealthStatus.DEGRADED,
                "任意機能を利用できません。",
                "値が設定されていません。",
            )
        return self._from_call(
            result,
            result.status,
            ok if result.status == HealthStatus.HEALTHY else "確認に失敗しました。",
            result.failure_reason,
        )

    @staticmethod
    def _from_call(
        result: _CallResult,
        status: HealthStatus,
        summary: str,
        failure_reason: str | None,
    ) -> HealthCheckItem:
        return HealthCheckItem(
            check_id=result.check_id,
            component=result.component,
            status=status,
            required=result.required,
            summary=summary,
            failure_reason=failure_reason,
            latency_ms=result.latency_ms,
            retryable=status == HealthStatus.UNAVAILABLE,
        )

    @staticmethod
    def _replace_metadata(
        item: HealthCheckItem, metadata: dict[str, object]
    ) -> HealthCheckItem:
        return HealthCheckItem(
            check_id=item.check_id,
            component=item.component,
            status=item.status,
            required=item.required,
            summary=item.summary,
            failure_reason=item.failure_reason,
            observed_at=item.observed_at,
            latency_ms=item.latency_ms,
            retryable=item.retryable,
            metadata=metadata,
        )

    @staticmethod
    def _condition(
        check_id: str,
        component: str,
        required: bool,
        condition: bool,
        ok: str,
        failure: str,
    ) -> HealthCheckItem:
        return PrepareStreamSessionUsecase._item(
            check_id,
            component,
            required,
            HealthStatus.HEALTHY if condition else HealthStatus.UNAVAILABLE,
            ok if condition else failure,
            failure_reason=None if condition else failure,
        )

    @staticmethod
    def _item(
        check_id: str,
        component: str,
        required: bool,
        status: HealthStatus,
        summary: str,
        *,
        failure_reason: str | None = None,
        retryable: bool = False,
    ) -> HealthCheckItem:
        return HealthCheckItem(
            check_id=check_id,
            component=component,
            status=status,
            required=required,
            summary=summary,
            failure_reason=failure_reason,
            retryable=retryable,
        )

    def _rejected_result(
        self,
        command: StreamPreparationCommand,
        started_at: datetime,
        reason: str,
        *,
        version_mismatch: bool = False,
    ) -> StreamPreparationResult:
        return StreamPreparationResult(
            session_id=command.session_id,
            trace_id=command.trace_id,
            status="rejected",
            ready=False,
            checks=(),
            failure_reasons=(reason,),
            started_at=started_at,
            completed_at=utc_now(),
            version_mismatch=version_mismatch,
        )

    def _cancel(
        self,
        command: StreamPreparationCommand,
        session: StreamSession,
        started_at: datetime,
    ) -> StreamPreparationResult:
        reason = "配信準備はcancelされました。"
        failed = self._sessions.save(
            session.transition(StreamSessionStatus.FAILED, failure_reasons=(reason,))
        )
        result = StreamPreparationResult(
            session_id=failed.session_id,
            trace_id=command.trace_id,
            status=failed.status.value,
            ready=False,
            checks=(),
            failure_reasons=(reason,),
            started_at=started_at,
            completed_at=utc_now(),
            canceled=True,
        )
        self._publisher.publish(result)
        return result

    def _publish_and_report(self, result: StreamPreparationResult) -> None:
        self._publisher.publish(result)
        if self._capability_reporter is None:
            return
        mapping = {
            "youtube.authentication": "youtube.authentication",
            "youtube.broadcast.resolvable": "youtube.broadcast.resolve",
            "youtube.stream.bound": "youtube.stream.inspect",
            "youtube.broadcast.status": "youtube.broadcast.inspect",
            "youtube.live_chat.available": "youtube.live_chat.inspect",
            "obs.connected": "obs.connect",
            "obs.idle": "obs.inspect.output",
            "obs.scene_collection": "obs.inspect.scene",
            "obs.start_scene": "obs.inspect.scene",
            "obs.audio_sources": "obs.inspect.audio",
            "obs.avatar_source": "obs.inspect.avatar_source",
            "tts.available": "tts.speak",
            "avatar.available": "avatar.control",
        }
        for item in result.checks:
            capability = mapping.get(item.check_id)
            if capability is not None:
                self._capability_reporter(
                    capability, item.status, item.failure_reason, item.observed_at
                )
        self._capability_reporter(
            "stream.session.prepare", HealthStatus.HEALTHY, None, result.completed_at
        )

    def _report_authentication_state(self, state: YouTubeAuthenticationState) -> None:
        if self._capability_reporter is None:
            return
        status = {
            YouTubeAuthenticationStatus.AUTHENTICATED: HealthStatus.HEALTHY,
            YouTubeAuthenticationStatus.AUTHENTICATION_IN_PROGRESS: HealthStatus.UNKNOWN,
            YouTubeAuthenticationStatus.AUTHENTICATION_REQUIRED: HealthStatus.UNAVAILABLE,
            YouTubeAuthenticationStatus.AUTHENTICATION_FAILED: HealthStatus.UNAVAILABLE,
        }[state.status]
        self._capability_reporter(
            "youtube.authentication",
            status,
            state.failure_reason,
            state.observed_at,
        )
