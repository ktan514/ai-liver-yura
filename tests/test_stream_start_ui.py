from __future__ import annotations

import os
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox, QScrollArea, QSizePolicy, QWidget

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
    settings_changed = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.approvals: list[tuple[str, int]] = []
        self.settings_updates: list[dict[str, object]] = []

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

    def update_settings(self, payload: dict[str, object]) -> None:
        self.settings_updates.append(payload)

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


def test_start_button_allows_fake_youtube_only_with_real_obs_and_confirmation(
    monkeypatch: object,
) -> None:
    app = application()
    controller = FakeController()
    window = StreamPreparationWindow(controller)  # type: ignore[arg-type]
    controller.session_changed.emit(snapshot(youtube="fake", obs="obs_websocket"))
    app.processEvents()
    assert window.start_button.isEnabled() is True

    controller.session_changed.emit(snapshot(youtube="google", obs="fake"))
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
        width, height = window.window_size_for_available(
            available_width, available_height
        )
        assert width <= available_width
        assert height <= available_height

    width, height = window.window_size_for_available(1920, 1080)
    assert 0.66 <= width / 1280 <= 0.70
    assert 0.66 <= height / 900 <= 0.70

    screen = app.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    assert window.width() <= available.width()
    assert window.height() <= available.height()
    assert window.width() >= window.minimumWidth()
    assert window.height() >= window.minimumHeight()
    assert window.maximumWidth() > window.minimumWidth()
    assert window.maximumHeight() > window.minimumHeight()
    assert window.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
    window.show()
    app.processEvents()
    for button in (
        window.prepare_button,
        window.start_button,
        window.end_button,
        window.emergency_button,
    ):
        assert button.isVisible()
    resized_width = min(available.width(), window.width() + 20)
    resized_height = min(available.height(), window.height() + 20)
    window.resize(resized_width, resized_height)
    app.processEvents()
    assert window.width() == resized_width
    assert window.height() == resized_height
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "概要",
        "コメント",
        "配信進行",
        "診断・ログ",
        "設定",
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


def test_settings_are_grouped_in_three_columns_and_apply_values_are_preserved() -> None:
    app = application()
    controller = FakeController()
    window = StreamPreparationWindow(controller)  # type: ignore[arg-type]
    window.show()

    window.resize(1100, 720)
    app.processEvents()
    assert window._settings_columns == 3  # noqa: SLF001 -- responsive layout contract
    assert (
        window.settings_grid.itemAtPosition(0, 0).widget() is window.log_settings_group
    )
    assert (
        window.settings_grid.itemAtPosition(0, 1).widget() is window.obs_settings_group
    )
    assert (
        window.settings_grid.itemAtPosition(0, 2).widget()
        is window.youtube_settings_group
    )
    assert (
        window.settings_grid.itemAtPosition(1, 0).widget()
        is window.common_settings_group
    )

    window.resize(800, 576)
    app.processEvents()
    assert window._settings_columns == 2  # noqa: SLF001 -- responsive layout contract
    assert (
        window.settings_grid.itemAtPosition(0, 0).widget() is window.log_settings_group
    )
    assert (
        window.settings_grid.itemAtPosition(0, 1).widget() is window.obs_settings_group
    )
    assert (
        window.settings_grid.itemAtPosition(1, 0).widget()
        is window.youtube_settings_group
    )
    assert (
        window.settings_grid.itemAtPosition(1, 1).widget()
        is window.common_settings_group
    )

    window.log_level.setCurrentText("DEBUG")
    window.obs_auto_refresh.setChecked(True)
    window.obs_interval.setValue(45)
    window.youtube_interval.setValue(75)
    window.ring_size.setValue(600)
    window.tabs.setCurrentIndex(0)
    window.tabs.setCurrentIndex(4)
    assert window.log_level.currentText() == "DEBUG"
    assert window.obs_interval.value() == 45

    window.apply_settings_button.click()
    app.processEvents()
    assert controller.settings_updates[-1]["level"] == "DEBUG"
    assert controller.settings_updates[-1]["obs_auto_refresh"] is True
    assert controller.settings_updates[-1]["obs_refresh_interval"] == 45
    assert controller.settings_updates[-1]["youtube_refresh_interval"] == 75
    assert controller.settings_updates[-1]["ring_buffer_size"] == 600
    window.close()


def test_small_layout_uses_scroll_areas_and_preserves_readable_minimums() -> None:
    app = application()
    window = StreamPreparationWindow(FakeController())  # type: ignore[arg-type]
    window.show()
    initial_width, initial_height = window.width(), window.height()
    window.resize(
        max(window.minimumWidth(), int(initial_width * 0.8)),
        max(window.minimumHeight(), int(initial_height * 0.8)),
    )
    app.processEvents()
    assert window.prepare_button.isVisible()
    assert window.emergency_button.isVisible()

    window.resize(720, 480)
    app.processEvents()

    assert isinstance(window.overview_scroll, QScrollArea)
    assert isinstance(window.settings_scroll, QScrollArea)
    assert window.overview_scroll.widgetResizable() is True
    assert window.settings_scroll.widgetResizable() is True
    assert (
        window.overview_scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert (
        window.settings_scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert window._overview_columns == 1  # noqa: SLF001 -- responsive layout contract
    assert window._operation_columns == 2  # noqa: SLF001 -- responsive layout contract
    assert window._settings_columns == 2  # noqa: SLF001 -- responsive layout contract
    assert window.main_layout.stretch(window.main_layout.indexOf(window.tabs)) == 1

    for card in (
        window.system_card,
        window.obs_card,
        window.youtube_card,
        window.progress_card,
    ):
        assert card.minimumHeight() > 0
        assert card.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Preferred
    for table in (
        window.responsibility_table,
        window.comment_table,
        window.step_table,
        window.timeline,
        window.diagnostic_table,
    ):
        assert table.minimumHeight() > table.horizontalHeader().height()

    assert window.overview_scroll.verticalScrollBar().maximum() > 0
    window.tabs.setCurrentIndex(4)
    window.settings_scroll.verticalScrollBar().setValue(
        window.settings_scroll.verticalScrollBar().maximum()
    )
    app.processEvents()
    assert window.apply_settings_button.isVisible()

    window.resize(1280, 720)
    app.processEvents()
    assert window._overview_columns == 2  # noqa: SLF001 -- responsive layout contract
    assert window._operation_columns == 3  # noqa: SLF001 -- responsive layout contract
    assert window._settings_columns == 3  # noqa: SLF001 -- responsive layout contract

    window.showMaximized()
    app.processEvents()
    assert window.isMaximized()
    assert window.prepare_button.isVisible()
    assert window.emergency_button.isVisible()
    window.showNormal()
    window.close()


@pytest.mark.parametrize(
    ("runtime_mode", "youtube", "obs", "expected"),
    [
        ("streaming_demo", "fake", "fake", "LOCAL DEMO / FAKE ADAPTERS"),
        ("streaming_demo", "fake", "obs_websocket", "YOUTUBE FAKE + OBS REAL"),
        ("standard", "google", "obs_websocket", "YOUTUBE REAL + OBS REAL"),
        ("standard", "fake", "disabled", "OBS DISABLED"),
        ("standard", "unknown", "unknown", "ADAPTER MODE UNKNOWN"),
    ],
)
def test_banner_uses_both_runtime_adapter_modes(
    runtime_mode: str, youtube: str, obs: str, expected: str
) -> None:
    app = application()
    window = StreamPreparationWindow(FakeController())  # type: ignore[arg-type]
    window._loaded(  # noqa: SLF001 -- bootstrap view contract
        {
            "health": {
                "runtime_mode": runtime_mode,
                "adapter_modes": {"youtube": youtube, "obs": obs},
            },
            "auth": {"adapter_type": youtube, "status": "authenticated"},
        }
    )
    app.processEvents()
    assert expected in window.banner.text()
    window.close()
