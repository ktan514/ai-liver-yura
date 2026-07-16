from __future__ import annotations

from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem

from app.domain.streaming import HealthCheckItem


class HealthCheckTable(QTableWidget):
    def __init__(self) -> None:
        super().__init__(0, 6)
        self.setHorizontalHeaderLabels(
            ["Check", "Component", "Status", "Required", "Summary", "Failure reason"]
        )

    def set_checks(self, checks: tuple[HealthCheckItem, ...]) -> None:
        self.setRowCount(len(checks))
        for row, item in enumerate(checks):
            values = (
                item.check_id,
                item.component,
                item.status.value,
                "yes" if item.required else "no",
                item.summary,
                item.failure_reason or "",
            )
            for column, value in enumerate(values):
                self.setItem(row, column, QTableWidgetItem(value))
        self.resizeColumnsToContents()
