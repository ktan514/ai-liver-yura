from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


WEB_ROOT = Path(__file__).parent / "web"


class StateHub:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._sequence = 0
        self._latest: dict[str, Any] | None = None

    def publish(self, state: dict[str, Any]) -> None:
        with self._condition:
            self._sequence += 1
            self._latest = state
            self._condition.notify_all()

    def snapshot(self) -> tuple[int, dict[str, Any] | None]:
        with self._condition:
            return self._sequence, self._latest

    def wait_next(
        self, sequence: int, timeout: float
    ) -> tuple[int, dict[str, Any] | None]:
        with self._condition:
            self._condition.wait_for(lambda: self._sequence > sequence, timeout)
            return self._sequence, self._latest


class TelemetryReceiver(threading.Thread):
    def __init__(self, hub: StateHub, host: str, port: int) -> None:
        super().__init__(name="YuraTelemetryReceiver", daemon=True)
        self._hub = hub
        self._host = host
        self._port = port

    def run(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self._host, self._port))
            while True:
                data, _ = receiver.recvfrom(65535)
                try:
                    payload = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if self._valid(payload):
                    self._hub.publish(payload)

    @staticmethod
    def _valid(value: object) -> bool:
        return (
            isinstance(value, dict)
            and value.get("schema_version") == 1
            and isinstance(value.get("emotion"), dict)
            and isinstance(value.get("drive"), dict)
        )


def handler_for(hub: StateHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "YuraInnerState/1.0"

        def handle(self) -> None:
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Browsers may discard a pre-opened or replaced connection before
                # sending the next request. This is a normal client disconnect.
                return

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/events":
                self._events()
                return
            if path == "/state":
                _, state = hub.snapshot()
                self._json(state or {"status": "waiting"})
                return
            self._static(path)

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            sequence, state = hub.snapshot()
            try:
                if state is not None:
                    self._send_event(state)
                while True:
                    next_sequence, next_state = hub.wait_next(sequence, 15.0)
                    if next_sequence == sequence:
                        self.wfile.write(b": heartbeat\n\n")
                    elif next_state is not None:
                        sequence = next_sequence
                        self._send_event(next_state)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send_event(self, state: dict[str, Any]) -> None:
            body = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
            self.wfile.write(f"event: state\ndata: {body}\n\n".encode())

        def _json(self, value: dict[str, Any]) -> None:
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path: str) -> None:
            relative = "index.html" if path == "/" else path.lstrip("/")
            target = (WEB_ROOT / relative).resolve()
            if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not target.is_file():
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
    parser = argparse.ArgumentParser(description="Yura inner-state visualizer")
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=8766)
    args = parser.parse_args()

    hub = StateHub()
    TelemetryReceiver(hub, args.udp_host, args.udp_port).start()
    server = ThreadingHTTPServer(
        (args.http_host, args.http_port),
        handler_for(hub),
    )
    print(f"Yura inner state: http://{args.http_host}:{args.http_port}")
    print(f"Telemetry UDP: {args.udp_host}:{args.udp_port}")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        time.sleep(0.05)


if __name__ == "__main__":
    main()
