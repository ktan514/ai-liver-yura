from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.admin_api.service import AdminApiService
from app.domain.streaming import (
    StreamEndRejected,
    StreamMainSegmentRejected,
    StreamOpeningRejected,
    StreamStartRejected,
)


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
    app = FastAPI(title="AI Liver Core Admin API", version="1.0.0")
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
        return {
            "status": "available",
            "runtime_mode": "streaming_demo" if service.demo_mode else "standard",
            "manual_check_log": service.manual_check_status(),
            "observed_at": service.broker.publish("runtime.connected", {}).occurred_at,
        }

    @app.post("/api/v1/manual-check/ui-events", status_code=202)
    async def manual_check_ui_event(payload: dict[str, Any]) -> Any:
        try:
            service.record_ui_operation(payload)
        except PermissionError:
            return _error("manual_check.disabled", "manual check logging is disabled", 404)
        except ValueError:
            return _error("request.invalid", "invalid manual check event", 422)
        return {"accepted": True}

    @app.post("/api/v1/demo/live-chat/messages", status_code=202)
    async def demo_live_chat_message(payload: dict[str, Any]) -> Any:
        if not service.demo_mode:
            return _error("demo.disabled", "demo endpoint is disabled", 404)
        try:
            return service.enqueue_demo_comment(payload)
        except ValueError:
            return _error("request.invalid", "text is required", 422)
        except RuntimeError as error:
            return _error(str(error), "live demo session is required", 409)

    @app.get("/api/v1/youtube/auth")
    async def auth_status() -> dict[str, Any]:
        return await service.auth_status()

    @app.post("/api/v1/youtube/auth/start", status_code=202)
    async def auth_start(payload: dict[str, Any]) -> Any:
        command_id = payload.get("command_id")
        if not isinstance(command_id, str) or not command_id:
            return _error("request.invalid", "command_id is required", 422)
        if not service.start_authentication(command_id):
            return _error("youtube.auth.in_progress", "authentication is already in progress", 409)
        return {"command_id": command_id, "accepted": True}

    @app.get("/api/v1/streaming/broadcasts")
    async def broadcasts() -> Any:
        try:
            return {"items": await service.broadcasts()}
        except Exception:
            return _error(
                "youtube.broadcast.list_failed", "broadcast list failed", 502, retryable=True
            )

    @app.post("/api/v1/streaming/broadcasts/refresh")
    async def refresh_broadcasts() -> Any:
        try:
            items = await service.broadcasts()
            service.broker.publish("youtube.broadcasts.updated", {"items": items})
            return {"items": items}
        except Exception:
            return _error(
                "youtube.broadcast.list_failed", "broadcast list failed", 502, retryable=True
            )

    @app.get("/api/v1/streaming/run-of-shows")
    async def run_of_shows() -> dict[str, Any]:
        return {"items": service.run_of_shows()}

    @app.get("/api/v1/streaming/session")
    async def session() -> Any:
        value = service.current_session()
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
            result = await service.prepare(payload)
        except (KeyError, TypeError, ValueError):
            return _error("request.invalid", "invalid preparation request", 422)
        except Exception:
            return _error("stream.prepare.failed", "stream preparation failed", 500, retryable=True)
        return result

    @app.get("/api/v1/capabilities")
    async def capabilities() -> dict[str, Any]:
        return {"items": service.capabilities()}

    @app.get("/api/v1/obs/status")
    async def obs_status() -> dict[str, Any]:
        return await service.refresh_obs()

    @app.post("/api/v1/obs/refresh")
    async def obs_refresh() -> dict[str, Any]:
        return await service.refresh_obs()

    @app.post("/api/v1/streaming/session/start/approve", status_code=202)
    async def approve_stream_start(payload: dict[str, Any]) -> Any:
        required = ("command_id", "session_id", "expected_state_version", "approved_by")
        if any(key not in payload for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            trace_id = service.approve_start(payload)
        except StreamStartRejected as error:
            status = 409 if error.code != "stream.session.not_found" else 404
            return _error(error.code, "stream start approval rejected", status)
        except (TypeError, ValueError):
            return _error("request.invalid", "invalid approval request", 422)
        return {"accepted": True, "trace_id": trace_id}

    @app.get("/api/v1/streaming/session/start/status")
    async def stream_start_status() -> Any:
        value = service.start_status()
        return (
            value
            if value is not None
            else _error("stream.start.not_found", "stream start result not found", 404)
        )

    @app.get("/api/v1/streaming/session/opening")
    async def stream_opening_status() -> Any:
        value = service.opening_status()
        return value if value is not None else _error("opening.not_found", "opening not found", 404)

    @app.post("/api/v1/streaming/session/opening/retry")
    async def retry_stream_opening(payload: dict[str, Any]) -> Any:
        required = ("command_id", "session_id", "expected_activity_version")
        if any(key not in payload for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            return await service.retry_opening(payload)
        except StreamOpeningRejected as error:
            return _error(error.code, "opening retry rejected", 409)
        except (KeyError, TypeError, ValueError):
            return _error("request.invalid", "invalid opening retry", 422)

    @app.get("/api/v1/streaming/session/main-segment")
    async def stream_main_segment_status() -> Any:
        value = service.main_segment_status()
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
            return await service.retry_main_segment(payload)
        except StreamMainSegmentRejected as error:
            return _error(error.code, "main segment retry rejected", 409)
        except (KeyError, TypeError, ValueError):
            return _error("request.invalid", "invalid main segment retry", 422)

    @app.post("/api/v1/streaming/session/end/approve")
    async def approve_stream_end(payload: dict[str, Any]) -> Any:
        required = ("command_id", "session_id", "expected_state_version", "approved_by")
        if any(key not in payload for key in required):
            return _error("request.invalid", "required field is missing", 422)
        try:
            return await service.approve_end(payload)
        except StreamEndRejected as error:
            return _error(error.code, "stream end rejected", 409)

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
            return await service.emergency_stop(payload)
        except StreamEndRejected as error:
            return _error(error.code, "emergency stop rejected", 409)

    @app.get("/api/v1/streaming/session/end/status")
    async def stream_end_status() -> Any:
        value = service.end_status()
        return (
            value
            if value is not None
            else _error("stream.end.not_found", "end result not found", 404)
        )

    @app.get("/api/v1/streaming/session/lifecycle")
    async def stream_lifecycle() -> Any:
        value = service.lifecycle_status()
        return (
            value
            if value is not None
            else _error("stream.session.not_found", "stream session not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/status")
    async def comments_status() -> Any:
        value = service.comments_status()
        return (
            value
            if value is not None
            else _error("live_chat.poller_not_found", "comment poller not found", 404)
        )

    @app.post("/api/v1/streaming/session/comments/refresh-status")
    async def refresh_comments_status() -> Any:
        value = await service.refresh_comments_status()
        return (
            value
            if value is not None
            else _error("live_chat.poller_not_found", "comment poller not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/moderation/status")
    async def comments_moderation_status() -> Any:
        value = service.moderation_status()
        return (
            value
            if value is not None
            else _error("comment_moderation.not_found", "comment moderation not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/moderation/recent")
    async def comments_moderation_recent() -> Any:
        value = service.moderation_recent()
        return (
            value
            if value is not None
            else _error("comment_moderation.not_found", "comment moderation not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/ranking/status")
    async def comments_ranking_status() -> Any:
        value = service.ranking_status()
        return (
            value
            if value is not None
            else _error("comment_ranking.not_found", "comment ranking not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/ranking/top")
    async def comments_ranking_top() -> Any:
        value = service.ranking_top()
        return (
            value
            if value is not None
            else _error("comment_ranking.not_found", "comment ranking not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/selection/current")
    async def comments_selection_current() -> Any:
        value = service.current_comment_selection()
        return (
            value
            if value is not None
            else _error("comment_ranking.not_found", "comment ranking not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/response/status")
    async def comments_response_status() -> Any:
        value = service.comment_response_status()
        return (
            value
            if value is not None
            else _error("comment_response.not_found", "comment response not found", 404)
        )

    @app.get("/api/v1/streaming/session/comments/response/recent")
    async def comments_response_recent() -> Any:
        value = service.comment_response_recent()
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
            return await service.retry_comment_response(payload)
        except Exception as error:
            code = getattr(error, "code", "comment_response.retry_failed")
            return _error(str(code), "comment response retry rejected", 409)

    @app.get("/api/v1/events/stream")
    async def events(
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        queue = service.broker.subscribe(last_event_id)

        async def generate() -> AsyncIterator[str]:
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                        payload = json.dumps(event.as_dict())
                        yield (
                            f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload}\n\n"
                        )
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                service.broker.unsubscribe(queue)

        return StreamingResponse(generate(), media_type="text/event-stream")

    return app
