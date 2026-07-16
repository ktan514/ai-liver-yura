from __future__ import annotations

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.streaming import (
    RunOfShowSummary,
    YouTubeAuthenticationState,
    YouTubeAuthenticationStatus,
)
from app.ui.pyqt.stream_preparation_controller import StreamPreparationController
from app.ui.pyqt.stream_preparation_view_model import StreamPreparationViewModel
from app.ui.pyqt.widgets import BroadcastSelector, HealthCheckTable, StreamStatusPanel


class StreamPreparationWindow(QMainWindow):
    def __init__(self, controller: StreamPreparationController) -> None:
        super().__init__()
        self._controller = controller
        self.setWindowTitle("AI Liver 配信準備")
        content = QWidget()
        layout = QVBoxLayout(content)
        self.broadcast_selector = BroadcastSelector()
        self.run_of_show_selector = QComboBox()
        self.adapter_type_label = QLabel("unknown")
        self.authentication_status_label = QLabel("unknown")
        self.authentication_failure_label = QLabel("")
        self.authentication_failure_label.setWordWrap(True)
        self.authenticate_button = QPushButton("YouTube認証")
        self.reload_broadcasts_button = QPushButton("配信枠を再読込")
        layout.addWidget(QLabel("YouTube Adapter"))
        layout.addWidget(self.adapter_type_label)
        layout.addWidget(QLabel("YouTube認証状態"))
        layout.addWidget(self.authentication_status_label)
        layout.addWidget(self.authentication_failure_label)
        auth_buttons = QHBoxLayout()
        auth_buttons.addWidget(self.authenticate_button)
        auth_buttons.addWidget(self.reload_broadcasts_button)
        layout.addLayout(auth_buttons)
        layout.addWidget(QLabel("YouTube Broadcast"))
        layout.addWidget(self.broadcast_selector)
        layout.addWidget(QLabel("RunOfShow"))
        layout.addWidget(self.run_of_show_selector)
        buttons = QHBoxLayout()
        self.prepare_button = QPushButton("配信準備")
        self.prepare_button.setEnabled(False)
        self.start_button = QPushButton("配信開始（未実装）")
        self.start_button.setEnabled(False)
        self.reload_broadcasts_button.setEnabled(False)
        buttons.addWidget(self.prepare_button)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)
        self.status_panel = StreamStatusPanel()
        self.health_table = HealthCheckTable()
        layout.addWidget(self.status_panel)
        layout.addWidget(self.health_table)
        self.setCentralWidget(content)

        controller.broadcasts_loaded.connect(self.broadcast_selector.set_broadcasts)
        controller.adapter_type_loaded.connect(self.adapter_type_label.setText)
        controller.authentication_state_changed.connect(self._authentication_changed)
        controller.authentication_busy_changed.connect(self._authentication_busy_changed)
        controller.broadcast_loading_changed.connect(self._broadcast_loading_changed)
        controller.run_of_shows_loaded.connect(self._set_run_of_shows)
        controller.preparation_started.connect(self._preparation_started)
        controller.preparation_finished.connect(self._preparation_finished)
        controller.error_occurred.connect(self._show_error)
        self.prepare_button.clicked.connect(self._prepare)
        self.authenticate_button.clicked.connect(controller.authenticate_youtube)
        self.reload_broadcasts_button.clicked.connect(controller.reload_broadcasts)
        controller.load_options()

    def _set_run_of_shows(self, values: object) -> None:
        self.run_of_show_selector.clear()
        if not isinstance(values, tuple):
            return
        for item in values:
            if isinstance(item, RunOfShowSummary):
                self.run_of_show_selector.addItem(item.title, item.run_of_show_id)

    def _prepare(self) -> None:
        broadcast_id = self.broadcast_selector.currentData()
        run_of_show_id = self.run_of_show_selector.currentData()
        if not isinstance(broadcast_id, str) or not isinstance(run_of_show_id, str):
            self._show_error("配信枠とRunOfShowを選択してください。")
            return
        self._controller.prepare(
            broadcast_id,
            str(self.broadcast_selector.currentData(0x0100 + 1) or ""),
            run_of_show_id,
        )

    def _authentication_changed(self, value: object) -> None:
        if not isinstance(value, YouTubeAuthenticationState):
            return
        self.authentication_status_label.setText(value.status.value)
        self.authentication_failure_label.setText(value.failure_reason or "")
        authenticated = value.status == YouTubeAuthenticationStatus.AUTHENTICATED
        self.authenticate_button.setEnabled(not authenticated)
        self.reload_broadcasts_button.setEnabled(authenticated)
        self.prepare_button.setEnabled(authenticated and not self._controller.preparing)

    def _authentication_busy_changed(self, busy: bool) -> None:
        self.authenticate_button.setEnabled(not busy)
        self.reload_broadcasts_button.setEnabled(not busy)
        if busy:
            self.authentication_status_label.setText("authentication_in_progress")

    def _broadcast_loading_changed(self, loading: bool) -> None:
        self.reload_broadcasts_button.setEnabled(not loading)
        self.broadcast_selector.setEnabled(not loading)

    def _preparation_started(self) -> None:
        self.prepare_button.setEnabled(False)
        self.status_panel.update_status(
            status="preparing", ready=False, failure_reason="", last_checked="-"
        )

    def _preparation_finished(self, model: object) -> None:
        self.prepare_button.setEnabled(True)
        if not isinstance(model, StreamPreparationViewModel):
            return
        self.status_panel.update_status(
            status=model.status,
            ready=model.ready,
            failure_reason=model.failure_reason,
            last_checked=model.last_checked_at,
        )
        self.health_table.set_checks(model.result.checks)
        self.status_panel.update_youtube_statuses(
            {item.check_id: item.status.value for item in model.result.checks}
        )
        self.start_button.setEnabled(False)

    def _show_error(self, message: str) -> None:
        self.prepare_button.setEnabled(
            self._controller.authenticated and not self._controller.preparing
        )
        self.status_panel.update_status(
            status="failed", ready=False, failure_reason=message, last_checked="-"
        )

    def closeEvent(self, event: QCloseEvent | None) -> None:  # noqa: N802 - Qt API
        self._controller.close()
        super().closeEvent(event)
