from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class SpeechMemoryItem:
    """短期記憶に保持する直近発話。"""

    text: str
    activity_type: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConversationMemoryItem:
    role: str
    text: str
    counterpart_id: str | None = None
    display_name: str | None = None
    created_at: datetime | None = None


class ShortTermMemory:
    """直近の発話をメモリ上に保持する短期記憶。"""

    def __init__(
        self, max_speech_items: int = 5, max_conversation_items: int = 10
    ) -> None:
        self._speech_items: deque[SpeechMemoryItem] = deque(maxlen=max_speech_items)
        self._conversation_items: deque[ConversationMemoryItem] = deque(
            maxlen=max_conversation_items
        )
        self._trace_logger = TraceLogger()

    def add_speech(
        self,
        text: str,
        activity_type: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        """発話内容を短期記憶に追加する。"""

        normalized_text = text.strip()
        if not normalized_text:
            self._trace_logger.write(
                "short_term_memory:add_speech:skipped",
                reason="empty_text",
            )
            return

        memory_item = SpeechMemoryItem(
            text=normalized_text,
            activity_type=activity_type,
            created_at=created_at or datetime.now(timezone.utc),
        )
        self._speech_items.append(memory_item)
        self._conversation_items.append(
            ConversationMemoryItem(
                role="assistant",
                text=memory_item.text,
                created_at=memory_item.created_at,
            )
        )
        self._trace_logger.write(
            "short_term_memory:add_speech:added",
            text_length=len(memory_item.text),
            activity_type=memory_item.activity_type,
            memory_count=len(self._speech_items),
        )

    def add_user_input(
        self,
        text: str,
        *,
        counterpart_id: str | None = None,
        display_name: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        normalized_text = text.strip()
        if not normalized_text:
            return
        self._conversation_items.append(
            ConversationMemoryItem(
                role="user",
                text=normalized_text,
                counterpart_id=counterpart_id,
                display_name=display_name,
                created_at=created_at or datetime.now(timezone.utc),
            )
        )

    def recent_conversation(
        self, limit: int | None = None
    ) -> list[ConversationMemoryItem]:
        items = list(self._conversation_items)
        return items[-limit:] if limit is not None else items

    def build_recent_conversation_summary(self, limit: int = 6) -> str:
        lines: list[str] = []
        for item in self.recent_conversation(limit=limit):
            if item.role == "assistant":
                speaker = "ゆら"
            else:
                speaker = item.display_name or "ユーザー"
            lines.append(f"- {speaker}: {item.text}")
        return "\n".join(lines)

    def recent_speeches(self, limit: int | None = None) -> list[SpeechMemoryItem]:
        """直近発話を古い順で返す。"""

        speech_items = list(self._speech_items)
        if limit is not None:
            speech_items = speech_items[-limit:]

        self._trace_logger.write(
            "short_term_memory:recent_speeches",
            requested_limit=limit,
            returned_count=len(speech_items),
            memory_count=len(self._speech_items),
        )
        return speech_items

    def build_recent_speech_summary(self, limit: int = 3) -> str:
        """Prompt に渡しやすい直近発話の要約テキストを作る。"""

        speech_items = self.recent_speeches(limit=limit)
        if not speech_items:
            self._trace_logger.write(
                "short_term_memory:build_recent_speech_summary:empty",
                requested_limit=limit,
            )
            return ""

        summary = "\n".join(f"- {speech_item.text}" for speech_item in speech_items)
        self._trace_logger.write(
            "short_term_memory:build_recent_speech_summary:built",
            requested_limit=limit,
            item_count=len(speech_items),
            summary_length=len(summary),
        )
        return summary

    def clear(self) -> None:
        """短期記憶をクリアする。"""

        before_count = len(self._speech_items)
        self._speech_items.clear()
        self._conversation_items.clear()
        self._trace_logger.write(
            "short_term_memory:clear",
            before_count=before_count,
        )
