from __future__ import annotations

from datetime import datetime, timezone

from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType
from app.domain.topic import (
    InterruptedTopic,
    TopicContinuationDecision,
    TopicContinuationResult,
    TopicLifecycleStatus,
)


class TopicContinuationEvaluator:
    """中断話題の価値・感情・経過を組み合わせて次の進路を選ぶ。

    ユーザーの無反応や別発言を、元話題を続けてよい根拠として扱わない。
    同一話題の自律発話は短く閉じ、明示的な反応がない限り再開を抑制する。
    """

    def evaluate(
        self,
        topic: InterruptedTopic,
        *,
        emotion: EmotionState,
        drive: DriveState,
        now: datetime | None = None,
    ) -> TopicContinuationResult:
        current_time = now or datetime.now(timezone.utc)
        elapsed_minutes = self._elapsed_minutes(topic, current_time)
        continuity = max(
            0.0,
            1.0
            - min(1.0, elapsed_minutes / 10.0)
            - min(0.6, topic.interruption_turns * 0.12),
        )
        negative_mood = emotion.mood in {MoodType.ANGRY, MoodType.SAD, MoodType.TIRED}

        if topic.turn_count >= 2:
            return TopicContinuationResult(
                TopicContinuationDecision.ABANDON_ORIGINAL,
                ("autonomous_turn_limit_reached", "yield_turn_to_listener"),
            )

        if topic.interruption_turns > 0:
            if topic.importance >= 0.75 and topic.incompleteness >= 0.7:
                return TopicContinuationResult(
                    TopicContinuationDecision.SUSPEND_ORIGINAL,
                    ("listener_intervened", "important_unfinished_topic"),
                )
            return TopicContinuationResult(
                TopicContinuationDecision.ABANDON_ORIGINAL,
                ("listener_intervened", "do_not_self_resume_without_invitation"),
            )

        if negative_mood or emotion.talkativeness < 0.3:
            if topic.importance >= 0.65 and topic.incompleteness >= 0.55:
                return TopicContinuationResult(
                    TopicContinuationDecision.SUSPEND_ORIGINAL,
                    ("negative_emotion", "important_unfinished_topic"),
                )
            return TopicContinuationResult(
                TopicContinuationDecision.WAIT,
                ("negative_emotion", "speech_motivation_low"),
            )

        if topic.exhaustion >= 0.7:
            return TopicContinuationResult(
                TopicContinuationDecision.ABANDON_ORIGINAL,
                ("original_topic_exhausted", "yield_turn_to_listener"),
            )

        resume_score = (
            topic.importance * 0.28
            + topic.interest * 0.27
            + topic.incompleteness * 0.30
            + continuity * 0.15
            - topic.exhaustion * 0.30
        )
        if resume_score >= 0.72:
            decision = (
                TopicContinuationDecision.RESUME_WITH_REFRAMING
                if topic.status == TopicLifecycleStatus.SUSPENDED
                else TopicContinuationDecision.RESUME_ORIGINAL
            )
            return TopicContinuationResult(
                decision,
                ("resume_score_high", f"resume_score={resume_score:.3f}"),
                reintroduction_required=continuity < 0.9,
                selected_topic=topic.original_text,
            )

        if topic.interest >= 0.7 and topic.incompleteness >= 0.65:
            return TopicContinuationResult(
                TopicContinuationDecision.BRANCH_FROM_ORIGINAL,
                ("original_interest_remains", "substantial_unfinished_point"),
                selected_topic=topic.original_text,
            )

        if drive.should_start_autonomous_talk():
            return TopicContinuationResult(
                TopicContinuationDecision.START_NEW_TOPIC,
                ("original_value_low", "autonomous_drive_available"),
            )
        return TopicContinuationResult(
            TopicContinuationDecision.WAIT,
            ("original_value_low", "autonomous_drive_weak"),
        )

    @staticmethod
    def _elapsed_minutes(topic: InterruptedTopic, now: datetime) -> float:
        if topic.interrupted_at is None:
            return 0.0
        return max(0.0, (now - topic.interrupted_at).total_seconds() / 60.0)
