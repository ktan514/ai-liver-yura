from __future__ import annotations

import asyncio

from app.common.trace import TraceLogger

from app.domain.actions import ActionPlan, ActionType
from app.domain.events import AgentEvent, AgentEventType
from app.ports.event_publisher import EventPublisher
from app.runtime.short_term_memory import ShortTermMemory


class ExecuteActionUsecase:
    """ActionPlan を実行する最小 UseCase。

    初期段階では外部 TTS / OBS / Live2D へ接続せず、標準出力に出す。
    後で Channel Executor へ分割する。
    """

    def __init__(
        self,
        event_publisher: EventPublisher | None = None,
        short_term_memory: ShortTermMemory | None = None,
    ) -> None:
        self._event_publisher = event_publisher
        self._short_term_memory = short_term_memory or ShortTermMemory()

        self._trace_logger = TraceLogger()

    async def execute(self, action_plan: ActionPlan) -> None:
        self._trace_logger.write(
            "execute_action_usecase:execute:start",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            source_activity_id=action_plan.source_activity_id,
            text_length=len(action_plan.text),
            required_resources=[
                resource.value for resource in action_plan.required_resources
            ],
        )
        if action_plan.action_type == ActionType.SPEAK:
            self._trace_logger.write(
                "execute_action_usecase:speak:start",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                text_length=len(action_plan.text),
            )
            await self._publish_speech_event(AgentEventType.SPEECH_STARTED, action_plan)
            self._trace_logger.write(
                "execute_action_usecase:speak:speech_started_published",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            estimated_duration_seconds = self._estimate_speech_duration_seconds(
                action_plan.text
            )
            self._trace_logger.write(
                "execute_action_usecase:speak:estimated_duration",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                text_length=len(action_plan.text),
                estimated_duration_seconds=estimated_duration_seconds,
            )
            print(f"[{action_plan.action_type.value}] {action_plan.text}")
            await asyncio.sleep(estimated_duration_seconds)
            await self._publish_speech_event(AgentEventType.SPEECH_FINISHED, action_plan)
            self._trace_logger.write(
                "execute_action_usecase:speak:speech_finished_published",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            self._short_term_memory.add_speech(
                text=action_plan.text,
                activity_type=action_plan.action_type.value,
            )
            self._trace_logger.write(
                "execute_action_usecase:speak:short_term_memory_added",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                text_length=len(action_plan.text),
            )
            self._trace_logger.write(
                "execute_action_usecase:speak:finished",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            return

        if action_plan.action_type in (ActionType.ASK, ActionType.REACT):
            print(f"[{action_plan.action_type.value}] {action_plan.text}")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
            )
            return

        if action_plan.action_type == ActionType.OBSERVE:
            print("[observe]")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
            )
            return

        if action_plan.action_type == ActionType.UPDATE_SUBTITLE:
            print(f"[subtitle] {action_plan.text}")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                text_length=len(action_plan.text),
            )
            return

        if action_plan.action_type == ActionType.CHANGE_EXPRESSION:
            print(f"[expression] {action_plan.text}")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                text=action_plan.text,
            )
            return

        print(f"[{action_plan.action_type.value}] not implemented")
        self._trace_logger.write(
            "execute_action_usecase:execute:not_implemented",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
        )

    def _estimate_speech_duration_seconds(self, text: str) -> float:
        """テキスト長から疑似的な読み上げ予定時間を見積もる。"""

        chars_per_second = 8.0
        minimum_seconds = 1.0
        maximum_seconds = 20.0
        estimated_seconds = len(text) / chars_per_second
        return max(minimum_seconds, min(maximum_seconds, estimated_seconds))

    async def _publish_speech_event(
        self,
        event_type: AgentEventType,
        action_plan: ActionPlan,
    ) -> None:
        self._trace_logger.write(
            "execute_action_usecase:publish_speech_event:start",
            event_type=event_type.value,
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            publisher_exists=self._event_publisher is not None,
        )
        if self._event_publisher is None:
            self._trace_logger.write(
                "execute_action_usecase:publish_speech_event:skipped",
                reason="publisher_not_set",
                event_type=event_type.value,
                action_id=action_plan.action_id,
            )
            return

        await self._event_publisher.publish(
            AgentEvent(
                event_type=event_type,
                payload={
                    "action_id": action_plan.action_id,
                    "source_activity_id": action_plan.source_activity_id,
                    "text": action_plan.text,
                },
            )
        )
        self._trace_logger.write(
            "execute_action_usecase:publish_speech_event:published",
            event_type=event_type.value,
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
        )
