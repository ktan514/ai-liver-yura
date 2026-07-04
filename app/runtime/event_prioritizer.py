

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from app.domain.events import AgentEvent, AgentEventType


class EventPrioritizer(Protocol):
    """EventQueue投入前にイベント優先度を補正するPort。"""

    def prioritize(self, event: AgentEvent) -> AgentEvent:
        ...


class DefaultEventPrioritizer:
    """初期実装用のイベント優先度補正。

    user_text / user_speech は最優先寄りにし、
    youtube_comment はそれに次ぐ優先度にする。
    camera_frame / trend_updated は低めに扱う。
    """

    _BONUS_BY_EVENT_TYPE: dict[AgentEventType, int] = {
        AgentEventType.USER_TEXT: 50,
        AgentEventType.YOUTUBE_COMMENT: 40,
        AgentEventType.USER_SPEECH: 50,
        AgentEventType.SPEECH_FINISHED: 20,
        AgentEventType.CURIOSITY_PEAK: 15,
        AgentEventType.SILENCE_TIMEOUT: 8,
        AgentEventType.TREND_UPDATED: 5,
        AgentEventType.CAMERA_FRAME: 3,
        AgentEventType.ACTION_FAILED: 30,
    }

    def prioritize(self, event: AgentEvent) -> AgentEvent:
        bonus = self._BONUS_BY_EVENT_TYPE.get(event.event_type, 0)
        return replace(event, priority=event.priority + bonus)