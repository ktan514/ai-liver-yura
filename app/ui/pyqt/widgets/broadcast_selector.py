from __future__ import annotations

from PyQt6.QtWidgets import QComboBox

from app.domain.streaming import YouTubeBroadcastSummary


class BroadcastSelector(QComboBox):
    def set_broadcasts(self, broadcasts: object) -> None:
        self.clear()
        if not isinstance(broadcasts, tuple):
            return
        for item in broadcasts:
            if isinstance(item, YouTubeBroadcastSummary) and item.selectable:
                self.addItem(f"{item.title} [{item.broadcast_id}]", item.broadcast_id)
                index = self.count() - 1
                self.setItemData(index, item.title, role=0x0100 + 1)
