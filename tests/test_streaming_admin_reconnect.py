from __future__ import annotations

from typing import Any

from streaming_admin.ui import StreamPreparationController


class BootstrapClient:
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


def test_reconnect_bootstraps_once_per_disconnected_to_connected_transition() -> None:
    controller = StreamPreparationController(BootstrapClient())  # type: ignore[arg-type]
    calls: list[bool] = []
    controller.load = lambda: calls.append(True)  # type: ignore[method-assign]
    try:
        controller.core_connection_changed(False)
        controller.core_connection_changed(True)
        controller.core_connection_changed(True)
        assert calls == [True]
        controller.core_connection_changed(False)
        controller.core_connection_changed(True)
        assert calls == [True, True]
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
