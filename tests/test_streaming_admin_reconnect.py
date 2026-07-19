from __future__ import annotations

import threading
from typing import Any

import httpx
import pytest

from streaming_admin.client import CoreApiError
from streaming_admin.ui import StreamPreparationController


class BootstrapClient:
    def __init__(self) -> None:
        self.manual_events: list[str] = []

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}

    def auth_status(self) -> dict[str, Any]:
        return {"status": "authenticated"}

    def broadcasts(self) -> list[dict[str, Any]]:
        return [{"broadcast_id": "broadcast"}]

    def run_of_shows(self) -> list[dict[str, Any]]:
        return [{"run_of_show_id": "show"}]

    def capabilities(self) -> list[dict[str, Any]]:
        return [{"capability_id": "demo"}]

    def manual_check_ui_event(
        self, event: str, details: dict[str, Any] | None = None
    ) -> None:
        self.manual_events.append(event)


def test_reconnect_bootstraps_once_per_disconnected_to_connected_transition() -> None:
    controller = StreamPreparationController(BootstrapClient())  # type: ignore[arg-type]
    calls: list[bool] = []
    controller.load = lambda: calls.append(True)  # type: ignore[method-assign]
    connections: list[bool] = []
    controller.connection_changed.connect(connections.append)
    try:
        controller.core_connection_changed(False)
        controller.core_connection_changed(True)
        controller.core_connection_changed(True)
        assert calls == [True]
        controller.core_connection_changed(False)
        controller.core_connection_changed(True)
        assert calls == [True, True]
        assert connections == []
    finally:
        controller.close()


def test_close_stops_worker_and_sends_disconnect_once() -> None:
    client = BootstrapClient()
    controller = StreamPreparationController(client)  # type: ignore[arg-type]
    stops: list[bool] = []
    controller.add_shutdown_callback(lambda: stops.append(True))

    controller.close()
    controller.close()

    assert stops == [True]
    assert client.manual_events == ["streaming_admin_disconnected"]


@pytest.mark.parametrize(
    "error",
    [
        CoreApiError("runtime.unavailable", "offline", True),
        httpx.ConnectError("connection refused"),
    ],
)
def test_close_ignores_expected_disconnect_delivery_failure(error: Exception) -> None:
    client = BootstrapClient()

    def fail(event: str, details: dict[str, Any] | None = None) -> None:
        raise error

    client.manual_check_ui_event = fail  # type: ignore[method-assign]
    controller = StreamPreparationController(client)  # type: ignore[arg-type]

    controller.close()
    controller.close()


def test_callbacks_do_not_reconnect_or_update_ui_after_close() -> None:
    client = BootstrapClient()
    controller = StreamPreparationController(client)  # type: ignore[arg-type]
    loads: list[bool] = []
    connections: list[bool] = []
    controller.load = lambda: loads.append(True)  # type: ignore[method-assign]
    controller.connection_changed.connect(connections.append)
    controller.close()

    controller.core_connection_changed(True)
    controller.handle_event(
        type("Event", (), {"event_type": "youtube.auth.updated", "data": {}})()
    )

    assert loads == []
    assert connections == []


def test_successful_rest_request_marks_connected_and_clears_stale_error() -> None:
    controller = StreamPreparationController(BootstrapClient())  # type: ignore[arg-type]
    connections: list[bool] = []
    errors: list[str] = []
    completed = threading.Event()
    controller.connection_changed.connect(connections.append)
    controller.error_occurred.connect(errors.append)
    try:
        controller._submit(
            "probe", lambda: {}, lambda _: completed.set()
        )  # noqa: SLF001
        assert completed.wait(1)
        assert connections == [True]
        assert errors == [""]
    finally:
        controller.close()


def test_command_rejection_does_not_mark_rest_connection_disconnected() -> None:
    controller = StreamPreparationController(BootstrapClient())  # type: ignore[arg-type]
    controller._core_connected = True  # noqa: SLF001 -- established REST precondition
    connections: list[bool] = []
    errors: list[str] = []
    completed = threading.Event()
    controller.connection_changed.connect(connections.append)
    controller.error_occurred.connect(
        lambda value: (errors.append(value), completed.set())
    )

    def reject() -> object:
        raise CoreApiError("stream.command_rejected", "command rejected")

    try:
        controller._submit("command", reject, lambda _: None)  # noqa: SLF001
        assert completed.wait(1)
        assert connections == []
        assert errors == ["command rejected"]
    finally:
        controller.close()


def test_rest_unavailable_marks_connection_disconnected() -> None:
    controller = StreamPreparationController(BootstrapClient())  # type: ignore[arg-type]
    controller._core_connected = True  # noqa: SLF001 -- established REST precondition
    connections: list[bool] = []
    completed = threading.Event()
    controller.connection_changed.connect(
        lambda value: (connections.append(value), completed.set())
    )

    def unavailable() -> object:
        raise CoreApiError("runtime.unavailable", "offline", True)

    try:
        controller._submit("probe", unavailable, lambda _: None)  # noqa: SLF001
        assert completed.wait(1)
        assert connections == [False]
    finally:
        controller.close()


def test_broadcast_refresh_updates_slots_and_run_of_shows_without_full_reload() -> None:
    controller = StreamPreparationController(BootstrapClient())  # type: ignore[arg-type]
    broadcasts: list[object] = []
    run_of_shows: list[object] = []
    full_loads: list[object] = []
    controller.broadcasts_changed.connect(broadcasts.append)
    controller.run_of_shows_changed.connect(run_of_shows.append)
    controller.loaded.connect(full_loads.append)
    try:
        controller._broadcasts_refreshed(  # noqa: SLF001 -- signal routing contract
            {
                "broadcasts": [{"broadcast_id": "broadcast"}],
                "run_of_shows": [{"run_of_show_id": "show"}],
            }
        )
        assert broadcasts == [[{"broadcast_id": "broadcast"}]]
        assert run_of_shows == [[{"run_of_show_id": "show"}]]
        assert full_loads == []
    finally:
        controller.close()
