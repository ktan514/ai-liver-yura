from __future__ import annotations

from PyQt6.QtWidgets import QFormLayout, QLabel, QWidget


class StreamStatusPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QFormLayout(self)
        self.session_status = QLabel("created")
        self.ready_status = QLabel("no")
        self.failure_reason = QLabel("")
        self.failure_reason.setWordWrap(True)
        self.last_checked = QLabel("-")
        self.youtube_api_status = QLabel("unknown")
        self.youtube_broadcast_status = QLabel("unknown")
        self.youtube_stream_status = QLabel("unknown")
        self.youtube_live_chat_status = QLabel("unknown")
        layout.addRow("StreamSession", self.session_status)
        layout.addRow("開始可能", self.ready_status)
        layout.addRow("失敗理由", self.failure_reason)
        layout.addRow("最終確認", self.last_checked)
        layout.addRow("YouTube API", self.youtube_api_status)
        layout.addRow("YouTube Broadcast", self.youtube_broadcast_status)
        layout.addRow("YouTube Stream", self.youtube_stream_status)
        layout.addRow("YouTube Live Chat", self.youtube_live_chat_status)

    def update_status(
        self, *, status: str, ready: bool, failure_reason: str, last_checked: str
    ) -> None:
        self.session_status.setText(status)
        self.ready_status.setText("yes" if ready else "no")
        self.failure_reason.setText(failure_reason)
        self.last_checked.setText(last_checked)

    def update_youtube_statuses(self, statuses: dict[str, str]) -> None:
        self.youtube_api_status.setText(statuses.get("youtube.api.available", "unknown"))
        self.youtube_broadcast_status.setText(statuses.get("youtube.broadcast.status", "unknown"))
        self.youtube_stream_status.setText(statuses.get("youtube.stream.status", "unknown"))
        self.youtube_live_chat_status.setText(
            statuses.get("youtube.live_chat.available", "unknown")
        )
