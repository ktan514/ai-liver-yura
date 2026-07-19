from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

SECRET_KEYS = {
    "authorization",
    "access_token",
    "refresh_token",
    "token",
    "stream_key",
    "client_secret",
    "password",
    "admin_token",
    "api_key",
}
EMPTY_INDEX = QModelIndex()


def mask_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "***REDACTED***"
                if str(key).lower() in SECRET_KEYS
                else mask_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    return value


class ManualCheckLogModel(QAbstractTableModel):
    COLUMNS = (
        ("timestamp", "時刻"),
        ("source", "Source"),
        ("category", "Category"),
        ("event", "Event"),
        ("status", "Status"),
        ("session_id", "Session"),
        ("activity_id", "Activity"),
        ("reason", "Reason"),
    )

    def __init__(self, max_rows: int = 5000) -> None:
        super().__init__()
        self.max_rows = max_rows
        self._items: list[dict[str, Any]] = []
        self._visible: list[dict[str, Any]] = []
        self._filters = {
            "source": "",
            "category": "",
            "event": "",
            "status": "",
            "keyword": "",
        }

    def rowCount(self, parent: QModelIndex = EMPTY_INDEX) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent: QModelIndex = EMPTY_INDEX) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        value = self._visible[index.row()].get(self.COLUMNS[index.column()][0])
        return "" if value is None else str(value)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:  # noqa: N802
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            return self.COLUMNS[section][1]
        return super().headerData(section, orientation, role)

    def append(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        self.beginResetModel()
        self._items.extend(mask_secrets(item) for item in items)
        self._items = self._items[-self.max_rows :]
        self._apply()
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._items.clear()
        self._visible.clear()
        self.endResetModel()

    def set_filters(self, **filters: str) -> None:
        self.beginResetModel()
        self._filters.update(
            {key: value.strip().casefold() for key, value in filters.items()}
        )
        self._apply()
        self.endResetModel()

    def item(self, row: int) -> dict[str, Any] | None:
        return self._visible[row] if 0 <= row < len(self._visible) else None

    def detail(self, row: int) -> str:
        item = self.item(row)
        return (
            json.dumps(item, ensure_ascii=False, indent=2) if item is not None else ""
        )

    def _apply(self) -> None:
        keyword_fields = (
            "event",
            "status",
            "reason",
            "category",
            "source",
            "session_id",
            "activity_id",
        )
        visible = []
        for item in self._items:
            if any(
                self._filters[key]
                and self._filters[key] not in str(item.get(key) or "").casefold()
                for key in ("source", "category", "event", "status")
            ):
                continue
            keyword = self._filters["keyword"]
            if keyword and not any(
                keyword in str(item.get(key) or "").casefold() for key in keyword_fields
            ):
                continue
            visible.append(item)
        self._visible = visible
