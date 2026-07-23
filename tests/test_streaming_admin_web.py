from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx

COMPONENT_ROOT = Path(__file__).parents[1] / "gui" / "yura-streaming-admin"
sys.path.insert(0, str(COMPONENT_ROOT))

from client import CoreApiClient, CoreApiError  # noqa: E402
from server import StreamingAdminService  # noqa: E402

from config import AdminClientConfig  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"operator": "web-operator"})()
        self.prepared: dict[str, Any] | None = None
        self.started: tuple[str, str, int, str] | None = None

    def health(self) -> dict[str, Any]:
        return {"status": "healthy", "runtime_mode": "streaming_demo"}

    def auth_status(self) -> dict[str, Any]:
        return {"status": "authenticated"}

    def broadcasts(self, refresh: bool = False) -> list[dict[str, Any]]:
        return [{"broadcast_id": "broadcast-1", "title": "Demo"}]

    def run_of_shows(self) -> list[dict[str, Any]]:
        return [{"run_of_show_id": "default", "title": "Default"}]

    def capabilities(self) -> list[dict[str, Any]]:
        return []

    def session(self) -> dict[str, Any]:
        return {"session_id": "session-1", "state_version": 3, "status": "ready"}

    def start_status(self) -> dict[str, Any]:
        return {"status": "ready"}

    def opening_status(self) -> dict[str, Any]:
        return {"status": "pending"}

    def main_segment_status(self) -> dict[str, Any]:
        return {"status": "pending"}

    def end_status(self) -> dict[str, Any]:
        return {"status": "pending"}

    def lifecycle(self) -> dict[str, Any]:
        return {"lifecycle_class": "prepared"}

    def comments_status(self) -> dict[str, Any]:
        return {"status": "running"}

    def moderation_status(self) -> dict[str, Any]:
        return {"status": "running"}

    def ranking_status(self) -> dict[str, Any]:
        return {"status": "running", "top": []}

    def comment_response_status(self) -> dict[str, Any]:
        return {"status": "idle"}

    def console_snapshot(self) -> dict[str, Any]:
        return {"current_state": "ready", "services": []}

    def prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.prepared = payload
        return {"status": "preparing"}

    def approve_start(
        self, command_id: str, session_id: str, version: int, operator: str
    ) -> dict[str, Any]:
        self.started = (command_id, session_id, version, operator)
        return {"status": "accepted"}


def test_web_bootstrap_collects_the_console_state() -> None:
    service = StreamingAdminService(FakeClient())  # type: ignore[arg-type]

    value = service.bootstrap()

    assert value["health"]["runtime_mode"] == "streaming_demo"
    assert value["broadcasts"][0]["broadcast_id"] == "broadcast-1"
    assert value["console"]["current_state"] == "ready"
    assert value["comments"]["status"] == "running"


def test_web_actions_add_server_side_command_metadata() -> None:
    client = FakeClient()
    service = StreamingAdminService(client)  # type: ignore[arg-type]

    service.action("prepare", {"broadcast_id": "broadcast-1", "run_of_show_id": "default"})
    service.action("start", {"session_id": "session-1", "state_version": 3})

    assert client.prepared is not None
    assert client.prepared["command_id"]
    assert client.prepared["broadcast_id"] == "broadcast-1"
    assert client.started is not None
    assert client.started[1:] == ("session-1", 3, "web-operator")


def test_core_api_client_reports_core_unavailable(monkeypatch: Any) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "request", fail)
    client = CoreApiClient(AdminClientConfig())
    try:
        client.health()
    except CoreApiError as error:
        assert error.code == "runtime.unavailable"
        assert error.retryable is True
    else:
        raise AssertionError("CoreApiError was not raised")
