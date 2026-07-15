from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from app.domain.events import AgentEvent


@dataclass(slots=True)
class EventBuffer:
    """EventQueue投入前のイベント保持バッファ。

    役割:
    - 通常イベントは投入順に全件保持する
    - replace_key を持つイベントは同じキーの最新イベントだけ保持する

    例:
    - user_text / youtube_comment は全件保持する
    - camera_frame / silence_timeout は最新だけ保持する
    """

    _normal_events: deque[AgentEvent] = field(default_factory=deque)
    _replaceable_events: dict[str, AgentEvent] = field(default_factory=dict)

    def put(self, event: AgentEvent) -> None:
        """イベントをバッファへ投入する。"""
        if event.replace_key is not None:
            self._replaceable_events[event.replace_key] = event
            return

        self._normal_events.append(event)

    def drain(self) -> list[AgentEvent]:
        """保持中のイベントを取り出し、バッファを空にする。

        通常イベントを先に返し、replace_key を持つ最新イベントを後に返す。
        replaceable イベント同士の順序は、dict の挿入順に従う。
        """
        events = list(self._normal_events)
        events.extend(self._replaceable_events.values())

        self.clear()
        return events

    def clear(self) -> None:
        """バッファを空にする。"""
        self._normal_events.clear()
        self._replaceable_events.clear()

    def is_empty(self) -> bool:
        """バッファが空かどうかを返す。"""
        return not self._normal_events and not self._replaceable_events
