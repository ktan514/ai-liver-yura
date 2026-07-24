from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.domain.conversation_flow import (
    ConversationFloorState,
    ConversationFlowState,
    ConversationOrigin,
    OpenPrompt,
    SpeechPurpose,
    SpeechRecord,
    UserResponseKind,
)


@dataclass(frozen=True, slots=True)
class ConversationTurnPolicy:
    user_topic_max_autonomous_turns: int = 1
    autonomous_topic_max_turns: int = 2
    task_topic_max_turns: int | None = None
    game_topic_max_turns: int | None = None
    default_yield_seconds: float = 30.0
    open_prompt_ttl_seconds: float = 300.0

    def max_turns_for(self, origin: ConversationOrigin) -> int | None:
        if origin == ConversationOrigin.USER:
            return self.user_topic_max_autonomous_turns
        if origin == ConversationOrigin.AUTONOMOUS:
            return self.autonomous_topic_max_turns
        if origin == ConversationOrigin.TASK:
            return self.task_topic_max_turns
        return self.game_topic_max_turns


class ConversationFlowController:
    """発話権、ユーザー反応、発話目的、未回答問いを一元管理する。"""

    def __init__(
        self,
        state: ConversationFlowState | None = None,
        policy: ConversationTurnPolicy | None = None,
    ) -> None:
        self.state = state or ConversationFlowState()
        self.policy = policy or ConversationTurnPolicy()

    def on_user_input(
        self,
        kind: UserResponseKind,
        *,
        topic: str | None = None,
        now: datetime | None = None,
    ) -> None:
        self.state.record_user_response(kind, topic=topic, now=now)

    def begin_response(self) -> None:
        self.state.begin_response()

    def begin_autonomous_talk(self) -> bool:
        if not self.can_start_autonomous_talk():
            return False
        self.state.begin_autonomous_talk()
        return True

    def record_output(
        self,
        text: str,
        purpose: SpeechPurpose,
        *,
        topic: str | None = None,
        subject: str | None = None,
        sentiment: str | None = None,
        imagery: tuple[str, ...] = (),
        now: datetime | None = None,
        return_floor: bool = True,
    ) -> SpeechRecord:
        record = SpeechRecord(
            text=text,
            purpose=purpose,
            topic=topic,
            subject=subject,
            sentiment=sentiment,
            imagery=imagery,
            created_at=now or datetime.now(timezone.utc),
        )
        self.state.record_agent_output(record, return_floor=return_floor)
        return record

    def can_start_autonomous_talk(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if self.state.floor_state == ConversationFloorState.RESPONDING:
            return False
        if self.state.floor_state == ConversationFloorState.YIELDING_TO_USER:
            started = self.state.yield_started_at
            if started is None:
                return False
            if current < started + timedelta(seconds=self.policy.default_yield_seconds):
                return False
        maximum = self.policy.max_turns_for(self.state.topic_origin)
        if maximum is not None and self.state.same_topic_turns >= maximum:
            return False
        return True

    def complete_yield_if_elapsed(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        started = self.state.yield_started_at
        if (
            self.state.floor_state == ConversationFloorState.YIELDING_TO_USER
            and started is not None
            and current >= started + timedelta(seconds=self.policy.default_yield_seconds)
        ):
            self.state.finish_yield()
            return True
        return False

    def register_open_prompt(
        self,
        text: str,
        *,
        topic: str | None = None,
        now: datetime | None = None,
    ) -> OpenPrompt:
        created_at = now or datetime.now(timezone.utc)
        prompt = OpenPrompt(
            prompt_id=str(uuid4()),
            text=text,
            topic=topic,
            created_at=created_at,
            expires_at=created_at
            + timedelta(seconds=self.policy.open_prompt_ttl_seconds),
        )
        self.state.open_prompts = [*self.state.active_open_prompts(created_at), prompt]
        return prompt

    def resolve_open_prompt(self, prompt_id: str) -> OpenPrompt | None:
        selected = next(
            (prompt for prompt in self.state.open_prompts if prompt.prompt_id == prompt_id),
            None,
        )
        if selected is not None:
            self.state.open_prompts = [
                prompt for prompt in self.state.open_prompts if prompt.prompt_id != prompt_id
            ]
        return selected
