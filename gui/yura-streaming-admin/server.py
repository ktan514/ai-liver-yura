from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
from collections import deque
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from client import CoreApiClient, CoreApiError, EventStreamClient
from config import AdminClientConfig

WEB_ROOT = Path(__file__).parent / "web"
MAX_JSON_BYTES = 64 * 1024
EVENT_COALESCE_SECONDS = 0.25


class WebEventHub:
    """Small fan-out buffer between the Core SSE worker and browsers."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._sequence = 0
        self._events: deque[tuple[int, dict[str, Any]]] = deque(maxlen=256)

    def publish(self, event: dict[str, Any]) -> None:
        with self._condition:
            self._sequence += 1
            self._events.append((self._sequence, event))
            self._condition.notify_all()

    def wait_after(self, sequence: int, timeout: float) -> tuple[int, list[dict[str, Any]]]:
        with self._condition:
            self._condition.wait_for(lambda: self._sequence > sequence, timeout)
            return self._sequence, [event for number, event in self._events if number > sequence]


class StreamingAdminService:
    """Browser-facing facade. Core credentials never leave this process."""

    def __init__(self, client: CoreApiClient) -> None:
        self.client = client

    @staticmethod
    def _optional(callback: Callable[[], Any]) -> Any:
        try:
            return callback()
        except CoreApiError as error:
            if error.code.endswith("not_found"):
                return None
            raise

    def bootstrap(self) -> dict[str, Any]:
        """Return one consistent snapshot without probing absent session resources."""

        health = self.client.health()
        auth = self.client.auth_status()
        broadcasts = self.client.broadcasts()
        run_of_shows = self.client.run_of_shows()
        capabilities = self.client.capabilities()
        session = self._optional(self.client.session)
        console = self._optional(self.client.console_snapshot)

        result: dict[str, Any] = {
            "health": health,
            "auth": auth,
            "broadcasts": broadcasts,
            "run_of_shows": run_of_shows,
            "capabilities": capabilities,
            "session": session,
            "start": None,
            "opening": None,
            "main_segment": None,
            "end": None,
            "lifecycle": None,
            "comments": None,
            "moderation": None,
            "ranking": None,
            "comment_response": None,
            "console": console,
        }

        if session is None:
            return result

        result.update(
            {
                "start": self._optional(self.client.start_status),
                "opening": self._optional(self.client.opening_status),
                "main_segment": self._optional(self.client.main_segment_status),
                "end": self._optional(self.client.end_status),
                "lifecycle": self._optional(self.client.lifecycle),
                "comments": self._optional(self.client.comments_status),
                "moderation": self._optional(self.client.moderation_status),
                "ranking": self._optional(self.client.ranking_status),
                "comment_response": self._optional(self.client.comment_response_status),
            }
        )
        return result

    def action(self, name: str, payload: dict[str, Any]) -> Any:
        command_id = str(uuid4())
        session_id = str(payload.get("session_id") or "")
        version = int(payload.get("state_version") or 0)
        actions: dict[str, Callable[[], Any]] = {
            "authenticate": lambda: self.client.start_auth(command_id),
            "refresh-broadcasts": lambda: {
                "broadcasts": self.client.broadcasts(True),
                "run_of_shows": self.client.run_of_shows(),
            },
            "refresh-obs": lambda: self.client.refresh_obs(),
            "refresh-youtube": lambda: {
                "auth": self.client.auth_status(),
                "broadcasts": self.client.broadcasts(True),
            },
            "prepare": lambda: self.client.prepare(
                {
                    "command_id": command_id,
                    "session_id": None,
                    "broadcast_id": str(payload.get("broadcast_id") or ""),
                    "run_of_show_id": str(payload.get("run_of_show_id") or ""),
                    "expected_state_version": None,
                }
            ),
            "start": lambda: self.client.approve_start(
                command_id, session_id, version, self.client.config.operator
            ),
            "end": lambda: self.client.approve_end(command_id, session_id, version),
            "emergency-stop": lambda: self.client.emergency_stop(
                command_id,
                session_id,
                version,
                str(payload.get("reason_code") or "operator_requested"),
            ),
            "retry-opening": lambda: self.client.retry_opening(
                command_id,
                session_id,
                int(payload.get("activity_version") or 0),
            ),
            "retry-main": lambda: self.client.retry_main_segment(
                command_id,
                session_id,
                str(payload.get("activity_id") or ""),
                int(payload.get("activity_version") or 0),
            ),
            "retry-comment": lambda: self.client.retry_comment_response(
                {
                    "command_id": command_id,
                    "session_id": session_id,
                    "activity_id": str(payload.get("activity_id") or ""),
                    "selection_id": str(payload.get("selection_id") or ""),
                    "expected_activity_version": int(payload.get("activity_version") or 0),
                }
            ),
            "demo-comment": lambda: self.client.enqueue_demo_comment(
                {
                    **payload,
                    "test_case_id": str(payload.get("test_case_id") or uuid4()),
                }
            ),
            "diagnostics-save": lambda: self.client.save_diagnostics(),
        }
        callback = actions.get(name)
        if callback is None:
            raise KeyError(name)
        return callback()


def handler_for(service: StreamingAdminService, hub: WebEventHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "YuraStreamingAdmin/2.0"

        def handle(self) -> None:
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/bootstrap":
                self._call(service.bootstrap)
            elif path == "/api/diagnostics":
                self._call(service.client.diagnostics)
            elif path == "/api/settings":
                self._call(service.client.settings)
            elif path == "/events":
                self._events()
            else:
                self._static(path)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path.startswith("/api/actions/"):
                name = path.removeprefix("/api/actions/")
                payload = self._read_json()
                if payload is None:
                    self.send_error(HTTPStatus.BAD_REQUEST, "invalid JSON")
                    return
                self._call(lambda: service.action(name, payload))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_PATCH(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/settings":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            payload = self._read_json()
            if payload is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "invalid JSON")
                return
            self._call(lambda: service.client.update_settings(payload))

        def _call(self, callback: Callable[[], Any]) -> None:
            try:
                value = callback()
            except KeyError:
                self._json(
                    {"error": {"code": "admin.action_not_found", "message": "未対応の操作です。"}},
                    HTTPStatus.NOT_FOUND,
                )
            except (CoreApiError, ValueError, TypeError) as error:
                status = (
                    HTTPStatus.SERVICE_UNAVAILABLE
                    if isinstance(error, CoreApiError) and error.code == "runtime.unavailable"
                    else HTTPStatus.BAD_REQUEST
                )
                self._json(
                    {
                        "error": {
                            "code": getattr(error, "code", "admin.invalid_request"),
                            "message": str(error),
                            "retryable": bool(getattr(error, "retryable", False)),
                        }
                    },
                    status,
                )
            else:
                self._json(value if isinstance(value, dict) else {"result": value})

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            sequence = 0
            try:
                self._send_event("connected", {"connected": True})
                while True:
                    sequence, events = hub.wait_after(sequence, 15)
                    if not events:
                        self.wfile.write(b": heartbeat\n\n")
                    else:
                        # Core can emit several related events for one state transition.
                        # Give them a short window to accumulate and notify the browser once.
                        time.sleep(EVENT_COALESCE_SECONDS)
                        sequence, trailing = hub.wait_after(sequence, 0)
                        if trailing:
                            events.extend(trailing)
                        self._send_event(
                            "core-event",
                            {
                                "count": len(events),
                                "events": events,
                            },
                        )
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def _send_event(self, name: str, value: dict[str, Any]) -> None:
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            self.wfile.write(f"event: {name}\ndata: {body}\n\n".encode())

        def _read_json(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length < 1 or length > MAX_JSON_BYTES:
                return None
            try:
                value = json.loads(self.rfile.read(length).decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return value if isinstance(value, dict) else None

        def _json(self, value: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path: str) -> None:
            relative = "index.html" if path == "/" else path.lstrip("/")
            target = (WEB_ROOT / relative).resolve()
            if WEB_ROOT.resolve() not in target.parents or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = target.read_bytes()
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            if "/events" not in str(args):
                super().log_message(format, *args)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Yura streaming admin web console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()

    config = AdminClientConfig.from_environment()
    service = StreamingAdminService(CoreApiClient(config))
    hub = WebEventHub()
    event_client = EventStreamClient(config)

    def on_event(event: object) -> None:
        hub.publish(
            {
                "event_id": str(getattr(event, "event_id", "")),
                "event_type": str(getattr(event, "event_type", "")),
                "data": getattr(event, "data", {}),
            }
        )

    event_thread = threading.Thread(
        target=event_client.run,
        args=(on_event, lambda connected: hub.publish({"connected": connected})),
        name="core-event-stream",
        daemon=True,
    )
    event_thread.start()
    server = ThreadingHTTPServer((args.host, args.port), handler_for(service, hub))
    print(f"Yura streaming admin: http://{args.host}:{args.port}")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        event_client.stop()
        server.shutdown()
        event_thread.join(timeout=config.timeout_seconds + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
