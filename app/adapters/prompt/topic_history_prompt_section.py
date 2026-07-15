from __future__ import annotations

from app.domain.topic import TopicHistory


class TopicHistoryPromptSection:
    def __init__(self, topic_history: TopicHistory | None = None) -> None:
        self._topic_history = topic_history

    def build(self) -> list[str]:
        if self._topic_history is None:
            return []

        entries = self._topic_history.recent_entries(limit=5)

        if not entries:
            return []

        lines = [
            "",
            "# 直近の話題履歴",
        ]

        for entry in entries:
            lines.append(f"- {entry.category.value}: {entry.summary}")

        rotation_hint = self._topic_history.rotation_hint()

        if rotation_hint is not None:
            lines.extend(
                [
                    "",
                    "# 話題選択の注意",
                    f"- {rotation_hint}",
                    "- 話題を変える場合は、直前の話題との共通点を使って自然に橋渡しする",
                    "- 同じ大テーマの細部だけを掘り続けない",
                ]
            )

        return lines
