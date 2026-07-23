from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


WEB_ROOT = Path(__file__).parent / "web"
MAX_JSON_BYTES = 32 * 1024
MAX_AUDIO_BYTES = 16 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventHub:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._sequence = 0
        self._events: deque[tuple[int, dict[str, Any]]] = deque(maxlen=256)
        self._messages: deque[dict[str, Any]] = deque(maxlen=100)

    def publish(self, event: dict[str, Any], *, remember: bool = False) -> None:
        with self._condition:
            self._sequence += 1
            self._events.append((self._sequence, event))
            if remember:
                self._messages.append(event)
            self._condition.notify_all()

    def snapshot(self) -> tuple[int, list[dict[str, Any]]]:
        with self._condition:
            return self._sequence, list(self._messages)

    def wait_after(
        self, sequence: int, timeout: float
    ) -> tuple[int, list[dict[str, Any]]]:
        with self._condition:
            self._condition.wait_for(lambda: self._sequence > sequence, timeout)
            events = [event for number, event in self._events if number > sequence]
            return self._sequence, events


@dataclass
class AudioItem:
    data: bytes
    finished: threading.Event = field(default_factory=threading.Event)
    status: str = "waiting"
    reason: str = ""


class AudioStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, AudioItem] = {}

    def add(self, data: bytes) -> tuple[str, AudioItem]:
        audio_id = uuid4().hex
        item = AudioItem(data)
        with self._lock:
            self._items[audio_id] = item
        return audio_id, item

    def data(self, audio_id: str) -> bytes | None:
        with self._lock:
            item = self._items.get(audio_id)
            return item.data if item is not None else None

    def finish(self, audio_id: str, status: str, reason: str = "") -> bool:
        with self._lock:
            item = self._items.get(audio_id)
            if item is None:
                return False
            item.status = status
            item.reason = reason
            item.finished.set()
            return True

    def remove(self, audio_id: str) -> None:
        with self._lock:
            self._items.pop(audio_id, None)

    def pending_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "type": "audio",
                    "audio_id": audio_id,
                    "url": f"/api/audio/{audio_id}",
                }
                for audio_id, item in self._items.items()
                if not item.finished.is_set()
            ]


def handler_for(
    hub: EventHub,
    audio_store: AudioStore,
    input_host: str,
    input_port: int,
    playback_timeout: float,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "YuraWebConversation/1.0"

        def handle(self) -> None:
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/events":
                self._events()
                return
            if path == "/api/history":
                _, messages = hub.snapshot()
                self._json({"messages": messages})
                return
            if path.startswith("/api/audio/"):
                self._audio(path.removeprefix("/api/audio/"))
                return
            self._static(path)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/input":
                self._input()
                return
            if path == "/api/output":
                self._output()
                return
            if path == "/api/audio":
                self._receive_audio()
                return
            if path.startswith("/api/audio/") and path.endswith("/complete"):
                audio_id = path.removeprefix("/api/audio/").removesuffix("/complete")
                self._complete_audio(audio_id)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def _input(self) -> None:
            payload = self._read_json()
            text = payload.get("text") if payload is not None else None
            if not isinstance(text, str) or not text.strip() or len(text.strip()) > 4000:
                self.send_error(HTTPStatus.BAD_REQUEST, "invalid text")
                return
            text = text.strip()
            message = {
                "type": "message",
                "id": uuid4().hex,
                "role": "user",
                "text": text,
                "observed_at": utc_now(),
            }
            packet = json.dumps(
                {"schema_version": 1, "type": "user_text", "text": text},
                ensure_ascii=False,
            ).encode("utf-8")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.sendto(packet, (input_host, input_port))
            hub.publish(message, remember=True)
            self._json({"status": "accepted", "id": message["id"]}, HTTPStatus.ACCEPTED)

        def _output(self) -> None:
            payload = self._read_json()
            text = payload.get("text") if payload is not None else None
            if not isinstance(text, str) or not text.strip():
                self.send_error(HTTPStatus.BAD_REQUEST, "invalid text")
                return
            message = {
                "type": "message",
                "id": uuid4().hex,
                "role": "yura",
                "kind": str(payload.get("kind") or "speak"),
                "action_id": str(payload.get("action_id") or ""),
                "text": text.strip(),
                "observed_at": utc_now(),
            }
            hub.publish(message, remember=True)
            self._json({"status": "accepted"}, HTTPStatus.ACCEPTED)

        def _receive_audio(self) -> None:
            data = self._read_body(MAX_AUDIO_BYTES)
            if not data:
                self.send_error(HTTPStatus.BAD_REQUEST, "empty audio")
                return
            audio_id, item = audio_store.add(data)
            hub.publish(
                {
                    "type": "audio",
                    "id": uuid4().hex,
                    "audio_id": audio_id,
                    "url": f"/api/audio/{audio_id}",
                    "observed_at": utc_now(),
                }
            )
            completed = item.finished.wait(playback_timeout)
            status = item.status if completed else "timeout"
            reason = item.reason if completed else "playback_timeout"
            audio_store.remove(audio_id)
            self._json({"status": status, "reason": reason, "audio_id": audio_id})

        def _audio(self, audio_id: str) -> None:
            data = audio_store.data(audio_id)
            if data is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _complete_audio(self, audio_id: str) -> None:
            payload = self._read_json() or {}
            status = payload.get("status", "completed")
            reason = payload.get("reason", "")
            if status not in {"completed", "failed", "skipped"}:
                self.send_error(HTTPStatus.BAD_REQUEST, "invalid status")
                return
            if not isinstance(reason, str):
                self.send_error(HTTPStatus.BAD_REQUEST, "invalid reason")
                return
            if not audio_store.finish(audio_id, str(status), reason[:500]):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._json({"status": "accepted"}, HTTPStatus.ACCEPTED)

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            sequence, messages = hub.snapshot()
            try:
                self._send_event(
                    "snapshot",
                    {"messages": messages, "audio": audio_store.pending_events()},
                )
                while True:
                    next_sequence, events = hub.wait_after(sequence, 15.0)
                    if not events:
                        self.wfile.write(b": heartbeat\n\n")
                    else:
                        for event in events:
                            self._send_event(str(event.get("type") or "event"), event)
                    sequence = next_sequence
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def _send_event(self, event_name: str, value: dict[str, Any]) -> None:
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            self.wfile.write(f"event: {event_name}\ndata: {body}\n\n".encode())

        def _read_body(self, maximum: int) -> bytes | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length < 1 or length > maximum:
                return None
            return self.rfile.read(length)

        def _read_json(self) -> dict[str, Any] | None:
            body = self._read_body(MAX_JSON_BYTES)
            if body is None:
                return None
            try:
                value = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return value if isinstance(value, dict) else None

        def _json(
            self, value: dict[str, Any], status: HTTPStatus = HTTPStatus.OK
        ) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Yura web conversation")
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8770)
    parser.add_argument("--input-host", default="127.0.0.1")
    parser.add_argument("--input-port", type=int, default=8771)
    parser.add_argument("--playback-timeout", type=float, default=180.0)
    args = parser.parse_args()

    server = ThreadingHTTPServer(
        (args.http_host, args.http_port),
        handler_for(
            EventHub(),
            AudioStore(),
            args.input_host,
            args.input_port,
            args.playback_timeout,
        ),
    )
    print(f"Yura web conversation: http://{args.http_host}:{args.http_port}")
    print(f"Yura input UDP: {args.input_host}:{args.input_port}")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
