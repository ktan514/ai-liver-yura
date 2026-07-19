from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from streaming_admin.logging import ManualCheckLogModel, ManualCheckLogReader


class ManualCheckLogWidget(QWidget):
    UPDATE_INTERVAL_MS = 1000
    MAX_ROWS = 5000

    def __init__(self, repository_root: Path | None = None) -> None:
        super().__init__()
        self.reader = ManualCheckLogReader(repository_root)
        self.model = ManualCheckLogModel(self.MAX_ROWS)
        self._new_count = 0
        self.status = QLabel("対象ログなし")
        self.path_label = QLabel("-")
        self.path_label.setTextInteractionFlags(self.path_label.textInteractionFlags())
        self.new_count = QLabel("")
        self.follow = QCheckBox("最新ログを自動追従")
        self.follow.setChecked(True)
        self.reload_button = QPushButton("再読込")
        self.clear_button = QPushButton("表示をクリア")
        self.source_filter = QLineEdit()
        self.category_filter = QLineEdit()
        self.event_filter = QLineEdit()
        self.status_filter = QLineEdit()
        self.keyword_filter = QLineEdit()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(False)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(100)

        root = QVBoxLayout(self)
        root.addWidget(self.status)
        root.addWidget(self.path_label)
        filters = QFormLayout()
        row = QHBoxLayout()
        for label, editor in (
            ("Source", self.source_filter),
            ("Category", self.category_filter),
            ("Event", self.event_filter),
            ("Status", self.status_filter),
            ("キーワード", self.keyword_filter),
        ):
            editor.setPlaceholderText(label)
            row.addWidget(editor)
        filters.addRow("Filter", row)
        root.addLayout(filters)
        controls = QHBoxLayout()
        controls.addWidget(self.reload_button)
        controls.addWidget(self.clear_button)
        controls.addWidget(self.follow)
        controls.addWidget(self.new_count)
        controls.addStretch(1)
        root.addLayout(controls)
        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        for editor in (
            self.source_filter,
            self.category_filter,
            self.event_filter,
            self.status_filter,
            self.keyword_filter,
        ):
            editor.textChanged.connect(self._apply_filters)
        self.reload_button.clicked.connect(self.reload)
        self.clear_button.clicked.connect(self.clear_display)
        self.follow.toggled.connect(self._follow_changed)
        selection_model = self.table.selectionModel()
        assert selection_model is not None
        selection_model.selectionChanged.connect(self._selection_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(self.UPDATE_INTERVAL_MS)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def configure(self, runtime_mode: str, manual_status: object) -> None:
        value = manual_status if isinstance(manual_status, dict) else {}
        enabled = bool(value.get("enabled"))
        path = value.get("path")
        self.reader.set_path(str(path) if path else None)
        self.path_label.setText(str(self.reader.path or "-"))
        if runtime_mode == "streaming_demo" and enabled:
            self.status.setText("記録中")
        elif runtime_mode == "streaming_demo":
            self.status.setText("手動確認ログは無効です")
        else:
            self.status.setText(
                "既存ログを表示" if self.reader.path else "対象ログなし"
            )
        self.poll()

    def poll(self) -> None:
        try:
            switched = self.reader.discover_newer()
            if switched:
                self.model.clear()
                self.path_label.setText(str(self.reader.path or "-"))
            scrollbar = self.table.verticalScrollBar()
            assert scrollbar is not None
            was_bottom = scrollbar.value() >= scrollbar.maximum() - 1
            items = self.reader.read_new()
            self.model.append(items)
            if items:
                if self.follow.isChecked() and was_bottom:
                    self.table.scrollToBottom()
                    self._new_count = 0
                else:
                    self._new_count += len(items)
                self._show_new_count()
        except OSError as error:
            self.status.setText(f"ログファイルを開けません: {type(error).__name__}")

    def reload(self) -> None:
        try:
            self.model.clear()
            self.model.append(self.reader.reload())
            self.path_label.setText(str(self.reader.path or "-"))
            self._new_count = 0
            self._show_new_count()
            if self.follow.isChecked():
                self.table.scrollToBottom()
        except OSError as error:
            self.status.setText(f"ログファイルを開けません: {type(error).__name__}")

    def clear_display(self) -> None:
        self.model.clear()
        self.reader.skip_existing()
        self.detail.clear()
        self._new_count = 0
        self._show_new_count()

    def _apply_filters(self) -> None:
        self.model.set_filters(
            source=self.source_filter.text(),
            category=self.category_filter.text(),
            event=self.event_filter.text(),
            status=self.status_filter.text(),
            keyword=self.keyword_filter.text(),
        )

    def _selection_changed(self) -> None:
        selection_model = self.table.selectionModel()
        assert selection_model is not None
        indexes = selection_model.selectedRows()
        self.detail.setPlainText(self.model.detail(indexes[0].row()) if indexes else "")

    def _follow_changed(self, enabled: bool) -> None:
        if enabled:
            self.table.scrollToBottom()
            self._new_count = 0
            self._show_new_count()

    def _show_new_count(self) -> None:
        self.new_count.setText(f"新着 {self._new_count}件" if self._new_count else "")
