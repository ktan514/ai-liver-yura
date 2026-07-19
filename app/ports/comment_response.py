from __future__ import annotations

from typing import Protocol

from app.plugins.youtube_streaming.domain import (
    CommentResponseHistoryEntry,
    StreamCommentResponseActivity,
)


class CommentResponseActivityRepository(Protocol):
    def create(
        self, activity: StreamCommentResponseActivity
    ) -> StreamCommentResponseActivity: ...
    def save(
        self, activity: StreamCommentResponseActivity
    ) -> StreamCommentResponseActivity: ...
    def get(self, activity_id: str) -> StreamCommentResponseActivity | None: ...
    def find_by_session(
        self, session_id: str
    ) -> StreamCommentResponseActivity | None: ...
    def find_by_selection(
        self, session_id: str, selection_id: str
    ) -> StreamCommentResponseActivity | None: ...
    def command_result(
        self, command_id: str
    ) -> StreamCommentResponseActivity | None: ...
    def save_command_result(
        self, command_id: str, activity: StreamCommentResponseActivity
    ) -> StreamCommentResponseActivity: ...


class CompletedCommentResponseHistoryRepository(Protocol):
    def save(self, item: CommentResponseHistoryEntry) -> None: ...
    def recent(
        self, session_id: str, limit: int = 20
    ) -> tuple[CommentResponseHistoryEntry, ...]: ...
