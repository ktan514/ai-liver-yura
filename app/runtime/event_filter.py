

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from app.domain.events import AgentEvent, AgentEventType


class EventFilter(Protocol):
    """EventQueue投入前にイベントを正規化・破棄判定するPort。"""

    def filter(self, event: AgentEvent) -> AgentEvent | None:
        ...


class DefaultEventFilter:
    """初期実装用のイベントフィルタ。

    役割:
    - EventQueue投入前にイベントを正規化する
    - 破棄可能イベントに discardable を設定する
    - 最新だけ残せばよいイベントに replace_key を設定する

    現時点ではイベントを実際に破棄しない。
    破棄・置換の実処理は EventQueue / EventBuffer 側で後続実装する。
    """

    def filter(self, event: AgentEvent) -> AgentEvent | None:
        if event.event_type == AgentEventType.CAMERA_FRAME:
            return replace(
                event,
                discardable=True,
                replace_key=event.replace_key or "camera_frame",
            )

        if event.event_type == AgentEventType.SILENCE_TIMEOUT:
            return replace(
                event,
                discardable=True,
                replace_key=event.replace_key or "silence_timeout",
            )

        return event