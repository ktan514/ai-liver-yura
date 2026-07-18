from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from app.admin_api.console import (
    AdapterCapabilities,
    DiagnosticRingBuffer,
    RuntimeLogSettings,
    freshness,
    operator_action_for,
    save_snapshot,
    timeline_entry,
)
from app.core.application.events import ApplicationEventBroker
from app.core.application.plugins import CommandDispatcher, PluginRegistry, QueryDispatcher


class AdminApiService:
    """Framework-facing gateway that knows only generic Core dispatch contracts."""

    def __init__(
        self,
        registry: PluginRegistry,
        broker: ApplicationEventBroker,
        runtime_status: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self.registry = registry
        self.broker = broker
        self._commands = CommandDispatcher(registry)
        self._queries = QueryDispatcher(registry)
        self._runtime_status = runtime_status or (
            lambda: {"runtime_mode": "standard", "manual_check_log": {"enabled": False}}
        )
        runtime = dict(self._runtime_status())
        self.log_settings = RuntimeLogSettings(runtime.get("log_settings"))
        self.diagnostics = DiagnosticRingBuffer(int(self.log_settings.values["ring_buffer_size"]))
        self.broker.add_observer(self._record_event)

    @property
    def demo_mode(self) -> bool:
        return self.has_capability("demo.live_chat.submit")

    async def command(self, capability: str, payload: Any = None) -> Any:
        return await self._commands.dispatch(capability, payload)

    async def query(self, capability: str, payload: Any = None) -> Any:
        return await self._queries.dispatch(capability, payload)

    def runtime_status(self) -> Mapping[str, Any]:
        return self._runtime_status()

    def _record_event(self, event_type: str, data: dict[str, Any], trace_id: str) -> None:
        self.diagnostics.append(timeline_entry(event_type, data, trace_id))

    def record_admin_operation(self, event: str, details: Mapping[str, Any] | None = None) -> None:
        self.broker.publish(
            "admin.operation.performed",
            {"operation": event, "details": dict(details or {})},
        )

    def adapter_capabilities(self) -> dict[str, Any]:
        runtime = dict(self.runtime_status())
        modes = runtime.get("adapter_modes", {})
        youtube_type = (
            str(modes.get("youtube", "unknown")) if isinstance(modes, Mapping) else "unknown"
        )
        overrides = runtime.get("streaming_capabilities")
        youtube_override = overrides.get("youtube") if isinstance(overrides, Mapping) else None
        youtube = AdapterCapabilities.for_adapter(
            youtube_type, youtube_override if isinstance(youtube_override, Mapping) else None
        )
        return {
            "youtube": {
                "adapter_type": youtube_type,
                "can_start_broadcast": youtube.can_start_broadcast,
                "can_stop_broadcast": youtube.can_stop_broadcast,
                "can_open_studio": youtube.can_open_studio,
                "can_check_status": youtube.can_check_status,
                "requires_operator_confirmation": youtube.requires_operator_confirmation,
                "studio_url": youtube.studio_url,
            }
        }

    async def console_snapshot(self) -> dict[str, Any]:
        async def optional(capability: str) -> Any:
            try:
                return await self.query(capability)
            except Exception:
                return None

        runtime = dict(self.runtime_status())
        session = await optional("stream.session.status.get")
        auth = await optional("youtube.auth.status")
        lifecycle = await optional("stream.lifecycle.status.get")
        opening = await optional("stream.opening.status.get")
        main = await optional("stream.main.status.get")
        end = await optional("stream.end.status.get")
        comments = await optional("stream.comment_pipeline.status.get")
        capabilities = self.adapter_capabilities()
        youtube_caps = AdapterCapabilities.for_adapter(
            str(capabilities["youtube"]["adapter_type"]), capabilities["youtube"]
        )
        status = (
            str(session.get("status", "created")) if isinstance(session, Mapping) else "created"
        )
        phase = (
            "ending"
            if status in {"ending", "closing"}
            else "starting"
            if status in {"ready", "starting"}
            else "idle"
        )
        auth_status = str(auth.get("status", "unknown")) if isinstance(auth, Mapping) else "unknown"
        observed = (
            session.get("observed_at") if isinstance(session, Mapping) else None
        ) or datetime.now(timezone.utc).isoformat()
        stale_after = int(self.log_settings.values["stale_after_seconds"])
        modes = (
            runtime.get("adapter_modes", {})
            if isinstance(runtime.get("adapter_modes"), Mapping)
            else {}
        )
        services = [
            {
                "name": "Core",
                "status": "healthy",
                "adapter_type": "core",
                "update_mode": "event_driven",
                "last_updated_at": observed,
                "freshness": freshness(observed, stale_after),
                "error_code": None,
                "error_message": None,
            },
            {
                "name": "OBS",
                "status": "healthy" if modes.get("obs") != "disabled" else "unavailable",
                "adapter_type": str(modes.get("obs", "unknown")),
                "update_mode": "automatic"
                if self.log_settings.values["obs_auto_refresh"]
                else "manual",
                "update_interval_seconds": int(self.log_settings.values["obs_refresh_interval"]),
                "next_update_in_seconds": int(self.log_settings.values["obs_refresh_interval"])
                if self.log_settings.values["obs_auto_refresh"]
                else None,
                "last_updated_at": observed,
                "freshness": freshness(observed, stale_after),
                "error_code": None,
                "error_message": None,
            },
            {
                "name": "YouTube",
                "status": auth_status,
                "adapter_type": str(modes.get("youtube", "unknown")),
                "update_mode": "automatic"
                if self.log_settings.values["youtube_auto_refresh"]
                else "event_driven",
                "update_interval_seconds": int(
                    self.log_settings.values["youtube_refresh_interval"]
                ),
                "next_update_in_seconds": int(self.log_settings.values["youtube_refresh_interval"])
                if self.log_settings.values["youtube_auto_refresh"]
                else None,
                "last_updated_at": observed,
                "freshness": freshness(observed, stale_after),
                "error_code": auth.get("failure_code") if isinstance(auth, Mapping) else None,
                "error_message": None,
            },
        ]
        steps = self._lifecycle_steps(session, opening, main, end)
        action = operator_action_for(youtube_caps, phase=phase, auth_status=auth_status)
        if (
            status not in {"ready", "starting", "ending", "closing"}
            and action["action_type"] == "authentication_required"
            and str(modes.get("youtube")) == "fake"
        ):
            action = operator_action_for(youtube_caps, phase="idle", auth_status="authenticated")
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "current_state": status,
            "current_message": self._current_message(status, action, opening),
            "runtime_state": runtime,
            "services": services,
            "adapter_capabilities": capabilities,
            "operator_action": action,
            "lifecycle_steps": steps,
            "responsibilities": self._responsibilities(steps, capabilities),
            "timeline": self.diagnostics.snapshot(),
            "comments": comments or {},
            "lifecycle": lifecycle or {},
            "log_settings": dict(self.log_settings.values),
        }

    @staticmethod
    def _current_message(status: str, action: Mapping[str, Any], opening: Any) -> str:
        if action.get("status") == "waiting":
            return str(action.get("title") or "人間の操作を待っています")
        if isinstance(opening, Mapping) and opening.get("status") == "failed":
            return "Openingに失敗しました。詳細を確認し、再試行または復旧判断を行ってください。"
        return {
            "live": "配信中です。Main進行を監視しています。",
            "ready": "配信準備が完了しました。配信開始を承認できます。",
            "ended": "配信は終了しました。",
        }.get(status, "状態を確認しています。")

    @staticmethod
    def _lifecycle_steps(session: Any, opening: Any, main: Any, end: Any) -> list[dict[str, Any]]:
        session_value = session if isinstance(session, Mapping) else {}
        status = str(session_value.get("status", "created"))
        definitions = [
            ("connection", "接続確認", "system"),
            ("youtube", "YouTube認証・配信枠確認", "system"),
            ("obs_start", "OBS配信出力開始", "system"),
            ("youtube_start", "YouTube公開開始", "system"),
            ("opening", "Opening", "system"),
            ("main", "Main", "system"),
            ("closing", "Closing", "system"),
            ("end", "配信終了", "system"),
        ]
        rank = {
            "created": 0,
            "preparing": 1,
            "ready": 2,
            "starting": 3,
            "live": 5,
            "ending": 6,
            "ended": 8,
            "failed": 0,
        }.get(status, 0)
        values: list[dict[str, Any]] = []
        for index, (step, title, owner) in enumerate(definitions, 1):
            source = (
                opening
                if step == "opening"
                else main
                if step == "main"
                else end
                if step in {"closing", "end"}
                else {}
            )
            source = source if isinstance(source, Mapping) else {}
            source_status = str(source.get("status") or source.get("closing_status") or "")
            step_status = (
                "failed"
                if source_status == "failed"
                else "completed"
                if index <= rank
                else "in_progress"
                if index == rank + 1
                else "not_started"
            )
            values.append(
                {
                    "step": step,
                    "title": title,
                    "status": step_status,
                    "started_at": source.get("started_at"),
                    "completed_at": source.get("completed_at"),
                    "owner": owner,
                    "error_code": source.get("error_code") or source.get("failure_code"),
                    "error_message": source.get("error_message") or source.get("failure_message"),
                    "retryable": bool(
                        source.get(
                            "retryable", step in {"opening", "main"} and step_status == "failed"
                        )
                    ),
                    "skippable": bool(source.get("skippable", False)),
                    "block_reason": source.get("block_reason"),
                }
            )
        return values

    @staticmethod
    def _responsibilities(
        steps: list[dict[str, Any]], capabilities: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        youtube = capabilities.get("youtube", {})
        manual_start = isinstance(youtube, Mapping) and not youtube.get("can_start_broadcast")
        manual_stop = isinstance(youtube, Mapping) and not youtube.get("can_stop_broadcast")
        fake_youtube = isinstance(youtube, Mapping) and youtube.get("adapter_type") == "fake"
        by_step = {item["step"]: item["status"] for item in steps}
        return [
            {
                "operation": "YouTube認証",
                "owner": "not_applicable" if fake_youtube else "operator",
                "status": "completed" if fake_youtube else by_step.get("youtube", "not_started"),
            },
            {
                "operation": "配信枠取得",
                "owner": "system",
                "status": by_step.get("youtube", "not_started"),
            },
            {
                "operation": "OBS接続・配信開始",
                "owner": "system",
                "status": by_step.get("obs_start", "not_started"),
            },
            {
                "operation": "YouTube公開開始",
                "owner": "operator" if manual_start else "system",
                "status": by_step.get("youtube_start", "not_started"),
            },
            {
                "operation": "Opening進行",
                "owner": "system",
                "status": by_step.get("opening", "not_started"),
            },
            {
                "operation": "YouTube公開終了",
                "owner": "operator" if manual_stop else "system",
                "status": by_step.get("end", "not_started"),
            },
            {
                "operation": "OBS配信停止",
                "owner": "system",
                "status": by_step.get("end", "not_started"),
            },
        ]

    def update_settings(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        result = self.log_settings.apply(changes)
        self.diagnostics.resize(int(result["ring_buffer_size"]))
        self.record_admin_operation("settings_changed", {"keys": sorted(changes)})
        return result

    async def diagnostic_snapshot(self) -> dict[str, Any]:
        console = await self.console_snapshot()
        events = self.diagnostics.snapshot()
        return {
            "generated_at": console["generated_at"],
            "runtime_state": console["runtime_state"],
            "adapter_states": console["services"],
            "recent_events": events,
            "recent_actions": [
                item
                for item in events
                if item.get("action_id") or item.get("event_name") == "admin.operation.performed"
            ],
            "recent_errors": [
                item for item in events if item.get("error_code") or item.get("result") == "failed"
            ],
            "configuration_summary": dict(self.log_settings.values),
        }

    async def save_diagnostics(self) -> dict[str, Any]:
        snapshot = await self.diagnostic_snapshot()
        path = save_snapshot(snapshot)
        self.record_admin_operation("diagnostics_saved", {"path": path})
        return {"saved": True, "path": path}

    async def start(self) -> None:
        await self.registry.start_all()

    async def stop(self) -> None:
        await self.registry.stop_all()

    def has_capability(self, capability: str) -> bool:
        try:
            self.registry.resolve_command(capability)
        except Exception:
            try:
                self.registry.resolve_query(capability)
            except Exception:
                return False
        return True


EventBroker = ApplicationEventBroker
