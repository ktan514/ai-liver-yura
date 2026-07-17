from __future__ import annotations

import os
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from streaming_admin.ui.stream_preparation_window import StreamPreparationWindow


class FakeController(QObject):
    loaded = pyqtSignal(object)
    auth_changed = pyqtSignal(object)
    broadcasts_changed = pyqtSignal(object)
    session_changed = pyqtSignal(object)
    obs_changed = pyqtSignal(object)
    start_changed = pyqtSignal(object)
    busy_changed = pyqtSignal(str, bool)
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.approvals: list[tuple[str, int]] = []

    def load(self) -> None:
        pass

    def authenticate(self) -> None:
        pass

    def refresh_broadcasts(self) -> None:
        pass

    def refresh_obs(self) -> None:
        pass

    def prepare(self, broadcast_id: str, run_id: str) -> None:
        pass

    def approve_start(self, session_id: str, version: int) -> None:
        self.approvals.append((session_id, version))

    def close(self) -> None:
        pass


def application() -> QApplication:
    return cast(QApplication, QApplication.instance() or QApplication([]))


def snapshot(*, youtube: str, obs: str) -> dict[str, object]:
    return {
        "session_id": "session",
        "state_version": 3,
        "status": "ready",
        "ready": True,
        "observed_at": "2026-01-01T00:00:00+00:00",
        "adapter_modes": {"youtube": youtube, "obs": obs},
        "checks": [],
        "failure_codes": [],
    }


def test_start_button_requires_ready_real_adapters_and_confirmation(monkeypatch: object) -> None:
    app = application()
    controller = FakeController()
    window = StreamPreparationWindow(controller)  # type: ignore[arg-type]
    controller.session_changed.emit(snapshot(youtube="fake", obs="obs_websocket"))
    app.processEvents()
    assert window.start_button.isEnabled() is False

    controller.session_changed.emit(snapshot(youtube="google", obs="obs_websocket"))
    app.processEvents()
    assert window.start_button.isEnabled() is True
    monkeypatch.setattr(  # type: ignore[attr-defined]
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    window.start_button.click()
    assert controller.approvals == [("session", 3)]
    window.close()


def test_window_geometry_tabs_and_fixed_emergency_controls() -> None:
    app = application()
    controller = FakeController()
    window = StreamPreparationWindow(controller)  # type: ignore[arg-type]

    for available_width, available_height in ((1366, 768), (1440, 900), (1920, 1080)):
        width, height = window.window_size_for_available(available_width, available_height)
        assert width <= available_width
        assert height <= available_height

    screen = app.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    assert window.width() <= available.width()
    assert window.height() <= available.height()
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "配信操作・状態",
        "コメント",
        "Timeline / 詳細",
        "ログ",
    ]

    central = window.centralWidget()
    assert central is not None
    for button in (
        window.prepare_button,
        window.start_button,
        window.end_button,
        window.emergency_button,
    ):
        assert central.isAncestorOf(button)
        assert not window.tabs.isAncestorOf(button)
    comment_tab = window.findChild(QWidget, "commentTab")
    detail_tab = window.findChild(QWidget, "detailTab")
    assert comment_tab is not None and comment_tab.isAncestorOf(window.demo_comment)
    assert detail_tab is not None and detail_tab.isAncestorOf(window.timeline)
    window.close()
