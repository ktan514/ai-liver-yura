from __future__ import annotations

from app.domain.emotions import EmotionAppraisal
from app.domain.events import AgentEvent, AgentEventType


class EmotionAppraiser:
    """Eventの確定事実を、発話表現とは独立した感情変化へ評価する。"""

    def appraise(self, event: AgentEvent) -> EmotionAppraisal:
        values = {
            AgentEventType.USER_TEXT: (0.02, 0.0, 0.03, "user_attention_received"),
            AgentEventType.USER_SPEECH: (0.03, 0.0, 0.03, "user_attention_received"),
            AgentEventType.YOUTUBE_COMMENT: (
                0.02,
                0.0,
                0.02,
                "viewer_attention_received",
            ),
            AgentEventType.ACTION_FAILED: (0.08, -0.08, -0.02, "action_failed"),
            AgentEventType.STREAM_STARTED: (0.05, 0.03, 0.02, "stream_started"),
            AgentEventType.STREAM_ENDED: (-0.04, 0.0, -0.02, "stream_ended"),
        }.get(event.event_type)
        if values is None:
            return EmotionAppraisal(source_event_id=event.event_id)
        arousal, valence, talkativeness, reason = values
        return EmotionAppraisal(
            arousal_delta=arousal,
            valence_delta=valence,
            talkativeness_delta=talkativeness,
            reason=reason,
            source_event_id=event.event_id,
        )
