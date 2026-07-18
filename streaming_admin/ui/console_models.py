from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


class DictTableModel(QAbstractTableModel):
    """Bounded table model for console DTO rows."""

    def __init__(
        self,
        columns: Sequence[tuple[str, str]],
        *,
        max_rows: int = 500,
    ) -> None:
        super().__init__()
        self.columns = tuple(columns)
        self.max_rows = max_rows
        self._source: list[dict[str, Any]] = []
        self._rows: list[dict[str, Any]] = []
        self._category = "all"
        self._errors_only = False

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        item = self._rows[index.row()]
        key = self.columns[index.column()][0]
        value = item.get(key)
        if role == Qt.ItemDataRole.DisplayRole:
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return "-" if value in {None, ""} else str(value)
        if role == Qt.ItemDataRole.ToolTipRole:
            return json.dumps(item, ensure_ascii=False, indent=2, default=str)
        if role == Qt.ItemDataRole.UserRole:
            return item
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section][1]
        return super().headerData(section, orientation, role)

    def set_rows(self, rows: Iterable[dict[str, Any]]) -> None:
        values = [dict(item) for item in rows]
        self.beginResetModel()
        self._source = values[-self.max_rows :]
        self._rows = self._filtered()
        self.endResetModel()

    def clear_display(self) -> None:
        self.beginResetModel()
        self._source = []
        self._rows = []
        self.endResetModel()

    def set_filter(self, category: str = "all", *, errors_only: bool = False) -> None:
        self.beginResetModel()
        self._category = category
        self._errors_only = errors_only
        self._rows = self._filtered()
        self.endResetModel()

    def item(self, row: int) -> dict[str, Any] | None:
        return dict(self._rows[row]) if 0 <= row < len(self._rows) else None

    def _filtered(self) -> list[dict[str, Any]]:
        values = self._source
        if self._category != "all":
            values = [item for item in values if item.get("category") == self._category]
        if self._errors_only:
            values = [
                item
                for item in values
                if item.get("error_code") or item.get("result") in {"failed", "error"}
            ]
        return list(values)


class TimelineTableModel(DictTableModel):
    def __init__(self, max_rows: int = 500) -> None:
        super().__init__(
            (
                ("timestamp", "時刻"),
                ("category", "区分"),
                ("event_name", "イベント"),
                ("result", "結果"),
                ("summary", "詳細"),
            ),
            max_rows=max_rows,
        )


class CommentTableModel(DictTableModel):
    def __init__(self, max_rows: int = 500) -> None:
        super().__init__(
            (
                ("timestamp", "時刻"),
                ("author", "ユーザー"),
                ("comment", "コメント"),
                ("moderation", "判定"),
                ("priority", "優先度"),
                ("status", "処理状態"),
                ("response", "応答"),
            ),
            max_rows=max_rows,
        )


class DiagnosticLogModel(TimelineTableModel):
    pass
