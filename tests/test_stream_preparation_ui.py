from __future__ import annotations

import os
from concurrent.futures import Future
from datetime import datetime, timezone
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.domain.streaming import (
    HealthCheckItem,
    HealthStatus,
    RunOfShowSummary,
    StreamPreparationResult,
    YouTubeAuthenticationState,
    YouTubeAuthenticationStatus,
    YouTubeBroadcastSummary,
)
from app.ui.pyqt import StreamPreparationController, StreamPreparationWindow


def resolved(value: object) -> Future[object]:
    future: Future[object] = Future()
    future.set_result(value)
    return future


class FakeGateway:
    def __init__(
        self,
        authentication_state: YouTubeAuthenticationState | None = None,
    ) -> None:
        self.prepare_future: Future[StreamPreparationResult] = Future()
        self.authenticate_future: Future[object] = resolved(
            YouTubeAuthenticationState(YouTubeAuthenticationStatus.AUTHENTICATED)
        )
        self.broadcast_future: Future[object] | None = None
        self.authentication_state = authentication_state or YouTubeAuthenticationState(
            YouTubeAuthenticationStatus.AUTHENTICATED
        )
        self.prepare_calls = 0
        self.broadcast_calls = 0
        self.closed = False

    def youtube_adapter_type(self) -> Future[object]:
        return resolved("fake")

    def youtube_authentication_state(self) -> Future[object]:
        return resolved(self.authentication_state)

    def authenticate_youtube(self) -> Future[object]:
        return self.authenticate_future

    def list_broadcasts(self) -> Future[object]:
        self.broadcast_calls += 1
        if self.broadcast_future is not None:
            return self.broadcast_future
        return resolved((YouTubeBroadcastSummary("broadcast", "テスト配信"),))

    def list_run_of_shows(self) -> Future[object]:
        return resolved((RunOfShowSummary("default", "標準", 60, 1, "default.yaml", "1"),))

    def prepare(
        self,
        *,
        broadcast_id: str,
        broadcast_title: str,
        run_of_show_id: str,
        requested_by: str = "pyqt_management_ui",
    ) -> Future[StreamPreparationResult]:
        del broadcast_id, broadcast_title, run_of_show_id, requested_by
        self.prepare_calls += 1
        return self.prepare_future

    def close(self) -> None:
        self.closed = True


def application() -> QApplication:
    instance = QApplication.instance()
    return cast(QApplication, instance) if instance is not None else QApplication([])


def test_ui_disables_double_click_and_displays_ready_result() -> None:
    app = application()
    gateway = FakeGateway()
    controller = StreamPreparationController(gateway)
    window = StreamPreparationWindow(controller)
    app.processEvents()
    assert window.broadcast_selector.currentData() == "broadcast"
    assert window.run_of_show_selector.currentData() == "default"

    window.prepare_button.click()
    assert window.prepare_button.isEnabled() is False
    assert controller.prepare("broadcast", "テスト配信", "default") is False
    assert gateway.prepare_calls == 1

    now = datetime.now(timezone.utc)
    gateway.prepare_future.set_result(
        StreamPreparationResult(
            session_id="session",
            trace_id="trace",
            status="ready",
            ready=True,
            checks=(
                HealthCheckItem(
                    "runtime.running",
                    "runtime",
                    HealthStatus.HEALTHY,
                    True,
                    "running",
                ),
            ),
            failure_reasons=(),
            started_at=now,
            completed_at=now,
        )
    )
    app.processEvents()
    assert window.status_panel.session_status.text() == "ready"
    assert window.health_table.rowCount() == 1
    assert window.start_button.isEnabled() is False
    window.close()
    assert gateway.closed is True


def test_ui_displays_failure_reason_and_closes_safely() -> None:
    app = application()
    gateway = FakeGateway()
    controller = StreamPreparationController(gateway)
    window = StreamPreparationWindow(controller)
    app.processEvents()
    window.prepare_button.click()
    now = datetime.now(timezone.utc)
    gateway.prepare_future.set_result(
        StreamPreparationResult(
            "session",
            "trace",
            "failed",
            False,
            (),
            ("OBS disconnected",),
            now,
            now,
        )
    )
    app.processEvents()
    assert "OBS disconnected" in window.status_panel.failure_reason.text()
    window.close()
    window.close()
    assert gateway.closed is True


def test_ui_authentication_is_non_blocking_and_reloads_broadcasts() -> None:
    app = application()
    gateway = FakeGateway(
        YouTubeAuthenticationState(
            YouTubeAuthenticationStatus.AUTHENTICATION_REQUIRED,
            "認証してください。",
        )
    )
    gateway.authenticate_future = Future()
    controller = StreamPreparationController(gateway)
    window = StreamPreparationWindow(controller)
    app.processEvents()
    assert window.adapter_type_label.text() == "fake"
    assert window.authentication_status_label.text() == "authentication_required"
    assert window.prepare_button.isEnabled() is False

    window.authenticate_button.click()
    assert window.authentication_status_label.text() == "authentication_in_progress"
    assert window.authenticate_button.isEnabled() is False
    gateway.authenticate_future.set_result(
        YouTubeAuthenticationState(YouTubeAuthenticationStatus.AUTHENTICATED)
    )
    app.processEvents()
    assert window.authentication_status_label.text() == "authenticated"
    assert gateway.broadcast_calls == 1
    assert window.broadcast_selector.currentData() == "broadcast"
    window.close()


def test_ui_disables_reload_while_loading_and_never_displays_token() -> None:
    app = application()
    gateway = FakeGateway()
    gateway.broadcast_future = Future()
    controller = StreamPreparationController(gateway)
    window = StreamPreparationWindow(controller)
    app.processEvents()
    assert window.reload_broadcasts_button.isEnabled() is False
    gateway.broadcast_future.set_exception(RuntimeError("安全なAPI失敗理由"))
    app.processEvents()
    assert "安全なAPI失敗理由" in window.status_panel.failure_reason.text()
    assert "token" not in window.status_panel.failure_reason.text().lower()
    window.close()
