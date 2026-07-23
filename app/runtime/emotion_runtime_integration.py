from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, replace
from typing import Any

from app.core.plugins.user_request import interpret_user_request
from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.runtime.agent_state import AgentState
from app.runtime.emotion_appraisal_service import EmotionAppraisalService
from app.runtime.emotion_context_builder import EmotionContextBuilder
from app.runtime.runtime_coordinator import RuntimeCoordinator


class EmotionAwareRuntimeCoordinator:
    """RuntimeCoordinatorを改変せず、感情評価を公開入口へ合成するDecorator。"""

    def __init__(
        self,
        delegate: RuntimeCoordinator,
        appraisal_service: EmotionAppraisalService,
    ) -> None:
        self._delegate = delegate
        self._appraisal_service = appraisal_service
        self._emotion_context_builder = EmotionContextBuilder()

    @property
    def agent_state(self) -> AgentState:
        return self._delegate.agent_state

    @property
    def appraisal_metrics(self) -> dict[str, int]:
        return self._appraisal_service.metrics

    async def publish_event(self, event: AgentEvent) -> None:
        await self.publish_events((event,))

    async def publish_events(self, events: Sequence[AgentEvent]) -> None:
        enriched_events: list[AgentEvent] = []
        for event in events:
            state = self._delegate.agent_state
            relationship = state.relationship_memory.current
            relationship_context = (
                relationship.as_context() if relationship is not None else {}
            )
            request_kind = None
            if event.event_type == AgentEventType.USER_TEXT:
                text = event.payload.get("text")
                if isinstance(text, str):
                    request_kind = interpret_user_request(text).kind.value
            enriched = await self._appraisal_service.enrich(
                event,
                relationship=relationship_context,
                situation=state.current_situation.as_context(),
                recent_context=self._recent_context(state),
                request_kind=request_kind,
            )
            emotion_context = self._emotion_context_builder.build(
                state.current_emotion,
                state.memory.emotion_history,
            )
            enriched_events.append(
                replace(
                    enriched,
                    payload={
                        **enriched.payload,
                        "emotion": asdict(emotion_context),
                    },
                )
            )
        await self._delegate.publish_events(enriched_events)

    async def submit_user_text(
        self,
        text: str,
        *,
        source: str = "external",
        authority: InputAuthority = InputAuthority.USER,
    ) -> None:
        await self.publish_event(
            AgentEvent(
                event_type=AgentEventType.USER_TEXT,
                payload={"text": text, "source": source},
                authority=authority,
            )
        )

    def diagnostic_snapshot(self) -> dict[str, object]:
        snapshot = dict(self._delegate.diagnostic_snapshot())
        snapshot["emotion_appraisal"] = self.appraisal_metrics
        return snapshot

    def __getattr__(self, name: str) -> Any:
        """既存RuntimeCoordinatorの公開APIを透過的に委譲する。"""

        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._delegate, name)

    @staticmethod
    def _recent_context(state: AgentState) -> str:
        history = state.memory.emotion_history[-3:]
        if not history:
            return ""
        return "\n".join(
            item.cause_summary or item.reason
            for item in history
            if item.cause_summary or item.reason
        )


def attach_emotion_runtime(
    coordinator: RuntimeCoordinator,
    appraisal_service: EmotionAppraisalService,
) -> EmotionAwareRuntimeCoordinator:
    """後付け書換えを行わず、Decoratorとして感情Runtimeを合成する。"""

    return EmotionAwareRuntimeCoordinator(coordinator, appraisal_service)
