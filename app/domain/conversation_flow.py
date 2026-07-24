from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ConversationFloorState(str, Enum):
    """現在の発話権と会話進行状態。"""

    IDLE = "idle"
    RESPONDING = "responding"
    YIELDING_TO_USER = "yielding_to_user"
    AUTONOMOUS_TALK = "autonomous_talk"


class UserResponseKind(str, Enum):
    """直近のユーザー反応を、観測可能な事実として分類する。"""

    NONE = "none"
    AGREEMENT = "agreement"
    QUESTION = "question"
    CORRECTION = "correction"
    TOPIC_CHANGE = "topic_change"
    REJECTION = "rejection"
    ELABORATION = "elaboration"


class SpeechPurpose(str, Enum):
    """発話が会話上果たす目的。"""

    ANSWER = "answer"
    EMPATHIZE = "empathize"
    SHARE_REACTION = "share_reaction"
    ASK_LIGHT_QUESTION = "ask_light_question"
    INTRODUCE_TOPIC = "introduce_topic"
    CLOSE_TOPIC = "close_topic"
    EXPLAIN = "explain"
    TASK_PROGRESS = "task_progress"


class ConversationOrigin(str, Enum):
    USER = "user"
    AUTONOMOUS = "autonomous"
    TASK = "task"
    GAME = "game"


@dataclass(frozen=True, slots=True)
class SpeechRecord:
    text: str
    purpose: SpeechPurpose
    topic: str | None = None
    subject: str | None = None
    sentiment: str | None = None
    imagery: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class OpenPrompt:
    prompt_id: str
    text: str
    topic: str | None
    created_at: datetime
    expires_at: datetime

    def is_active(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) < self.expires_at


@dataclass(slots=True)
class ConversationFlowState:
    """会話制御に必要な最小限の状態を保持する。"""

    floor_state: ConversationFloorState = ConversationFloorState.IDLE
    user_response_observed: bool = False
    user_response_kind: UserResponseKind = UserResponseKind.NONE
    last_user_input_at: datetime | None = None
    last_agent_output_at: datetime | None = None
    yield_started_at: datetime | None = None
    current_topic: str | None = None
    topic_origin: ConversationOrigin = ConversationOrigin.AUTONOMOUS
    same_topic_turns: int = 0
    recent_speeches: list[SpeechRecord] = field(default_factory=list)
    open_prompts: list[OpenPrompt] = field(default_factory=list)

    def begin_response(self) -> None:
        self.floor_state = ConversationFloorState.RESPONDING

    def begin_autonomous_talk(self) -> None:
        self.floor_state = ConversationFloorState.AUTONOMOUS_TALK

    def record_user_response(
        self,
        kind: UserResponseKind,
        *,
        now: datetime | None = None,
        topic: str | None = None,
    ) -> None:
        self.user_response_observed = True
        self.user_response_kind = kind
        self.last_user_input_at = now or datetime.now(timezone.utc)
        self.floor_state = ConversationFloorState.RESPONDING
        if kind == UserResponseKind.TOPIC_CHANGE:
            self.current_topic = topic
            self.same_topic_turns = 0
            self.topic_origin = ConversationOrigin.USER
        elif topic is not None:
            self.current_topic = topic

    def record_agent_output(
        self,
        speech: SpeechRecord,
        *,
        return_floor: bool = True,
    ) -> None:
        self.last_agent_output_at = speech.created_at
        if speech.topic is not None and speech.topic == self.current_topic:
            self.same_topic_turns += 1
        elif speech.topic is not None:
            self.current_topic = speech.topic
            self.same_topic_turns = 1
        self.recent_speeches = [*self.recent_speeches[-7:], speech]
        self.user_response_observed = False
        self.user_response_kind = UserResponseKind.NONE
        if return_floor:
            self.floor_state = ConversationFloorState.YIELDING_TO_USER
            self.yield_started_at = speech.created_at

    def finish_yield(self) -> None:
        self.floor_state = ConversationFloorState.IDLE

    def active_open_prompts(self, now: datetime | None = None) -> list[OpenPrompt]:
        current = now or datetime.now(timezone.utc)
        self.open_prompts = [prompt for prompt in self.open_prompts if prompt.is_active(current)]
        return list(self.open_prompts)
