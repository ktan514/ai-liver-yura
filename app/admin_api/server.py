from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.admin_api.service import AdminApiService
from app.core.contracts.plugins import CommandRejected


def _error(code: str, message: str, status: int, *, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "trace_id": str(uuid4()),
            }
        },
        status_code=status,
    )


def create_admin_api(service: AdminApiService, token: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(
        title="AI Liver Core Admin API",
        version="1.0.0",
        lifespan=lifespan,
    )
    configured_token = token if token is not None else os.getenv("AI_LIVER_ADMIN_API_TOKEN")

    @app.middleware("http")
    async def authenticate(request: Request, call_next: Any) -> Any:
        if configured_token:
            supplied = request.headers.get("authorization", "")
            if supplied != f"Bearer {configured_token}":
                return _error("request.unauthorized", "invalid admin API token", 401)
        return await call_next(request)

    @app.get("/api/v1/health")
    async def health() -> dict[str, Any]:
        status = service.runtime_status()
        return {
            "status": "available",
            "runtime_mode": status["runtime_mode"],
            "manual_check_log": status["manual_check_log"],
            "config_path": status.get("config_path"),
            "adapter_modes": status.get("adapter_modes", {}),
            "obs_connection": status.get("obs_connection", {}),
            "observed_at": service.broker.publish("runtime.connected", {}).occurred_at,
        }

    @app.post("/api/v1/manual-check/ui-events", status_code=202)
    async def manual_check_ui_event(payload: dict[str, Any]) -> Any:
        event = str(payload.get("event") or "")
        if not event:
            return _error("request.invalid", "event is required", 422)
        service.record_admin_operation(
            event,
            payload.get("details") if isinstance(payload.get("details"), dict) else {},
        )
        try:
            await service.command("manual_check.ui.record", payload)
        except CommandRejected as error:
            if error.reason_code != "manual_check.disabled":
                return _error("request.invalid", "invalid manual check event", 422)
        return {
            "accepted": True,
            "file_logged": bool(
                service.runtime_status().get("manual_check_log", {}).get("enabled", False)
            ),
        }

    @app.get("/api/v1/admin/console")
    async def admin_console() -> dict[str, Any]:
        return await service.console_snapshot()

    @app.get("/api/v1/admin/diagnostics")
    async def diagnostics() -> dict[str, Any]:
        return await service.diagnostic_snapshot()

    @app.post("/api/v1/admin/diagnostics/save")
    async def save_diagnostics() -> dict[str, Any]:
        return await service.save_diagnostics()

    @app.get("/api/v1/admin/settings")
    async def admin_settings() -> dict[str, Any]:
        return dict(service.log_settings.values)

    @app.patch("/api/v1/admin/settings")
    async def update_admin_settings(payload: dict[str, Any]) -> Any:
        try:
            return {"applied": True, "settings": service.update_settings(payload)}
        except (TypeError, ValueError) as error:
            return _error("settings.invalid", str(error), 422)

    @app.post("/api/v1/demo/live-chat/messages", status_code=202)
    async def demo_live_chat_message(payload: dict[str, Any]) -> Any:
        if not service.has_capability("demo.live_chat.submit"):
            return _error("demo.disabled", "demo endpoint is disabled", 404)
        try:
            return await service.command("demo.live_chat.submit", payload)
        except CommandRejected as error:
            if error.reason_code == "demo.live_session_required":
                return _error(error.reason_code, "live demo session is required", 409)
            return _error("request.invalid", "text is required", 422)

    @app.get("/api/v1/youtube/auth")
    async def auth_status() -> dict[str, Any]:
        return cast(dict[str, Any], await service.query("youtube.auth.status"))

    @app.post("/api/v1/youtube/auth/start", status_code=202)
    async def auth_start(payload: dict[str, Any]) -> Any:
        command_id = payload.get("command_id")
        if not isinstance(command_id, str) or not command_id:
            return _error("request.invalid", "command_id is required", 422)
        if not await service.command("youtube.auth.start", {"command_id": command_id}):
            return _error("youtube.auth.in_progress", "authentication is already in progress", 409)
        return {"command_id": command_id, "accepted": True}

    @app.get("/api/v1/streaming/broadcasts")
    async def broadcasts() -> Any:
        try:
            return {"items": await service.query("stream.broadcast.list")}
        except Exception:
            return _error(
                "youtube.broadcast.list_failed", "broadcast list failed", 502, retryable=True
            )

    @app.post("/api/v1/streaming/broadcasts/refresh")
    async def refresh_broadcasts() -> Any:
        try:
            items = await service.command("stream.broadcast.refresh")
            service.broker.publish("youtube.broadcasts.updated", {"items": items})
            return {"items": items}
        except Exception:
            return _error(
                "youtube.broadcast.list_failed", "broadcast list failed", 502, retryable=True
            )

    @app.get("/api/v1/streaming/run-of-shows")
    async def run_of_shows() -> dict[str, Any]:
        return {"items": await service.query("stream.run_of_show.list")}

    @app.get("/api/v1/streaming/session")
    async def session() -> Any:
        value = await service.query("stream.session.status.get")
        return (
            value
            if value is not None
            else _error("stream.session.not_found", "stream session not found", 404)
        )

    @app.post("/api/v1/streaming/session/prepare")
    async def prepare(payload: dict[str, Any]) -> Any:
        required = ("command_id", "broadcast_id", "run_of_show_id")
        if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            result = await service.command("stream.session.prepare", payload)
        except (KeyError, TypeError, ValueError):
            return _error("request.invalid", "invalid preparation request", 422)
        except Exception:
            return _error("stream.prepare.failed", "stream preparation failed", 500, retryable=True)
        return result

    @app.get("/api/v1/capabilities")
    async def capabilities() -> dict[str, Any]:
        return {"items": await service.query("stream.capability.status")}

    @app.get("/api/v1/obs/status")
    async def obs_status() -> dict[str, Any]:
        return cast(dict[str, Any], await service.query("obs.status.get"))

    @app.post("/api/v1/obs/refresh")
    async def obs_refresh() -> dict[str, Any]:
        return cast(dict[str, Any], await service.command("obs.status.refresh"))

    @app.post("/api/v1/streaming/session/start/approve", status_code=202)
    async def approve_stream_start(payload: dict[str, Any]) -> Any:
        required = ("command_id", "session_id", "expected_state_version", "approved_by")
        if any(key not in payload for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            trace_id = await service.command("stream.session.approve_start", payload)
        except CommandRejected as error:
            status = 404 if error.reason_code == "stream.session.not_found" else 409
            return _error(error.reason_code, "stream start approval rejected", status)
        except (TypeError, ValueError):
            return _error("request.invalid", "invalid approval request", 422)
        return {"accepted": True, "trace_id": trace_id}

    @app.get("/api/v1/streaming/session/start/status")
    async def stream_start_status() -> Any:
        value = await service.query("stream.start.status.get")
        return (
            value
            if value is not None
            else _error("stream.start.not_found", "stream start result not found", 404)
        )

    @app.get("/api/v1/streaming/session/opening")
    async def stream_opening_status() -> Any:
        value = await service.query("stream.opening.status.get")
        return value if value is not None else _error("opening.not_found", "opening not found", 404)

    @app.post("/api/v1/streaming/session/opening/retry")
    async def retry_stream_opening(payload: dict[str, Any]) -> Any:
        required = ("command_id", "session_id", "expected_activity_version")
        if any(key not in payload for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            return await service.command("stream.opening.retry", payload)
        except CommandRejected as error:
            return _error(error.reason_code, "opening retry rejected", 409)
        except (KeyError, TypeError, ValueError):
            return _error("request.invalid", "invalid opening retry", 422)

    @app.get("/api/v1/streaming/session/main-segment")
    async def stream_main_segment_status() -> Any:
        value = await service.query("stream.main.status.get")
        return (
            value
            if value is not None
            else _error("main_segment.not_found", "main segment not found", 404)
        )

    @app.post("/api/v1/streaming/session/main-segment/retry")
    async def retry_stream_main_segment(payload: dict[str, Any]) -> Any:
        required = ("command_id", "session_id", "activity_id", "expected_activity_version")
        if any(key not in payload for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            return await service.command("stream.main.retry", payload)
        except CommandRejected as error:
            return _error(error.reason_code, "main segment retry rejected", 409)
        except (KeyError, TypeError, ValueError):
            return _error("request.invalid", "invalid main segment retry", 422)

    @app.post("/api/v1/streaming/session/end/approve")
    async def approve_stream_end(payload: dict[str, Any]) -> Any:
        required = ("command_id", "session_id", "expected_state_version", "approved_by")
        if any(key not in payload for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            return await service.command("stream.end.normal", payload)
        except CommandRejected as error:
            return _error(error.reason_code, "stream end rejected", 409)

    @app.post("/api/v1/streaming/session/emergency-stop")
    async def emergency_stop(payload: dict[str, Any]) -> Any:
        required = (
            "command_id",
            "session_id",
            "expected_state_version",
            "requested_by",
            "reason_code",
        )
        if any(key not in payload for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            return await service.command("stream.end.emergency", payload)
        except CommandRejected as error:
            return _error(error.reason_code, "emergency stop rejected", 409)

    @app.get("/api/v1/streaming/session/end/status")
    async def stream_end_status() -> Any:
        value = await service.query("stream.end.status.get")
        return (
            value
            if value is not None
            else _error("stream.end.not_found", "end result not found", 404)
        )

    @app.get("/api/v1/streaming/session/lifecycle")
    async def stream_lifecycle() -> Any:
        value = await service.query("stream.lifecycle.status.get")
        return (
            value
            if value is not None
            else _error("stream.session.not_found", "stream session not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/status")
    async def comments_status() -> Any:
        value = await service.query("stream.comment_pipeline.status.get")
        return (
            value
            if value is not None
            else _error("live_chat.poller_not_found", "comment poller not found", 404)
        )

    @app.post("/api/v1/streaming/session/comments/refresh-status")
    async def refresh_comments_status() -> Any:
        value = await service.command("stream.comment.status.refresh")
        return (
            value
            if value is not None
            else _error("live_chat.poller_not_found", "comment poller not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/moderation/status")
    async def comments_moderation_status() -> Any:
        value = await service.query("stream.moderation.status.get")
        return (
            value
            if value is not None
            else _error("comment_moderation.not_found", "comment moderation not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/moderation/recent")
    async def comments_moderation_recent() -> Any:
        value = await service.query("stream.moderation.recent.list")
        return (
            value
            if value is not None
            else _error("comment_moderation.not_found", "comment moderation not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/ranking/status")
    async def comments_ranking_status() -> Any:
        value = await service.query("stream.ranking.status.get")
        return (
            value
            if value is not None
            else _error("comment_ranking.not_found", "comment ranking not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/ranking/top")
    async def comments_ranking_top() -> Any:
        value = await service.query("stream.ranking.top.list")
        return (
            value
            if value is not None
            else _error("comment_ranking.not_found", "comment ranking not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/selection/current")
    async def comments_selection_current() -> Any:
        value = await service.query("stream.selection.current.get")
        return (
            value
            if value is not None
            else _error("comment_ranking.not_found", "comment ranking not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/response/status")
    async def comments_response_status() -> Any:
        value = await service.query("stream.comment.response.status.get")
        return (
            value
            if value is not None
            else _error("comment_response.not_found", "comment response not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/response/recent")
    async def comments_response_recent() -> Any:
        value = await service.query("stream.comment.response.recent.list")
        return (
            value
            if value is not None
            else _error("comment_response.not_found", "comment response not found", 404)
        )

    @app.post("/api/v1/streaming/session/comments/response/retry")
    async def comments_response_retry(payload: dict[str, Any]) -> Any:
        required = (
            "command_id",
            "session_id",
            "activity_id",
            "selection_id",
            "expected_activity_version",
        )
        if any(key not in payload for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            return await service.command("stream.comment.response.retry", payload)
        except CommandRejected as error:
            return _error(error.reason_code, "comment response retry rejected", 409)

    @app.get("/api/v1/events/stream")
    async def events(
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        subscription = service.broker.subscribe(last_event_id)

        async def generate() -> AsyncIterator[str]:
            try:
                for event in subscription.replay_events:
                    payload = json.dumps(event.as_dict())
                    yield f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload}\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(subscription.live_queue.get(), timeout=15)
                        payload = json.dumps(event.as_dict())
                        yield (
                            f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload}\n\n"
                        )
                        if event.event_type == service.broker.RESYNC_EVENT_TYPE:
                            return
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                service.broker.unsubscribe(subscription)

        return StreamingResponse(generate(), media_type="text/event-stream")

    return app
