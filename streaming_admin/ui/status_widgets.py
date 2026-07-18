from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from streaming_admin.i18n.ja import status_label
from streaming_admin.ui.stream_preparation_view_model import local_time

STATUS_ICONS = {
    "healthy": "✓",
    "completed": "✓",
    "live": "✓",
    "in_progress": "↻",
    "preparing": "↻",
    "warning": "⚠",
    "degraded": "⚠",
    "failed": "✕",
    "unavailable": "✕",
    "not_started": "○",
    "waiting": "◷",
    "unknown": "?",
    "stale": "⚠",
}


def status_text(value: object) -> str:
    key = str(value or "unknown")
    return f"{STATUS_ICONS.get(key, '•')} {status_label(key)}"


class StatusCardWidget(QGroupBox):
    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(8, 8, 8, 8)
        self.form.setVerticalSpacing(4)
        self.fields: dict[str, QLabel] = {}

    def set_fields(self, values: dict[str, object]) -> None:
        for key, value in values.items():
            label = self.fields.get(key)
            if label is None:
                label = QLabel("-")
                label.setWordWrap(True)
                self.fields[key] = label
                self.form.addRow(key, label)
            label.setText(str(value if value not in {None, ""} else "-"))

    def set_service(self, value: dict[str, Any]) -> None:
        self.set_fields(
            {
                "状態": status_text(value.get("status")),
                "Adapter": value.get("adapter_type"),
                "更新方式": value.get("update_mode"),
                "更新間隔": f"{value.get('update_interval_seconds')}秒"
                if value.get("update_interval_seconds")
                else "-",
                "次回更新": f"約{value.get('next_update_in_seconds')}秒後"
                if value.get("next_update_in_seconds")
                else "手動更新またはイベント待ち",
                "最終更新": local_time(value.get("last_updated_at")),
                "状態の鮮度": status_text(value.get("freshness")),
                "エラー": value.get("error_message") or value.get("error_code") or "-",
            }
        )


class CurrentActionBanner(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(2)
        self.current = QLabel("現在：状態を確認中")
        self.current.setStyleSheet("font-size:18px;font-weight:bold")
        self.message = QLabel("Coreへ接続しています。")
        self.message.setWordWrap(True)
        root.addWidget(self.current)
        root.addWidget(self.message)

    def update_state(self, state: str, message: str, waiting: bool = False) -> None:
        self.current.setText(f"現在：{status_label(state)}")
        self.message.setText(message)
        color = "#fff3cd" if waiting else "#e8f5e9"
        self.setStyleSheet(
            f"CurrentActionBanner{{background:{color};padding:10px;border-radius:4px}}"
        )
