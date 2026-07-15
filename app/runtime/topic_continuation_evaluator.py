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
    """中断話題の価値・感情・経過を組み合わせて次の進路を選ぶ。"""

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
            1.0 - min(1.0, elapsed_minutes / 10.0) - min(0.6, topic.interruption_turns * 0.12),
        )
        negative_mood = emotion.mood in {MoodType.ANGRY, MoodType.SAD, MoodType.TIRED}

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
            if topic.interest >= 0.65 and topic.interruption_topics:
                return TopicContinuationResult(
                    TopicContinuationDecision.BRANCH_FROM_INTERRUPTION,
                    ("original_topic_exhausted", "interruption_candidate_available"),
                    selected_topic=topic.interruption_topics[-1],
                )
            return TopicContinuationResult(
                TopicContinuationDecision.ABANDON_ORIGINAL,
                ("original_topic_exhausted", "new_points_insufficient"),
            )

        resume_score = (
            topic.importance * 0.28
            + topic.interest * 0.27
            + topic.incompleteness * 0.30
            + continuity * 0.15
            - topic.exhaustion * 0.30
        )
        if resume_score >= 0.64:
            decision = (
                TopicContinuationDecision.RESUME_WITH_REFRAMING
                if topic.status == TopicLifecycleStatus.SUSPENDED or topic.interruption_turns >= 2
                else TopicContinuationDecision.RESUME_ORIGINAL
            )
            return TopicContinuationResult(
                decision,
                ("resume_score_high", f"resume_score={resume_score:.3f}"),
                reintroduction_required=continuity < 0.9 or topic.interruption_turns > 0,
                selected_topic=topic.original_text,
            )

        if topic.interruption_topics and drive.curiosity >= 0.65:
            return TopicContinuationResult(
                TopicContinuationDecision.BRANCH_FROM_INTERRUPTION,
                ("interruption_candidate_available", "curiosity_high"),
                selected_topic=topic.interruption_topics[-1],
            )

        if topic.interest >= 0.6 and topic.incompleteness >= 0.4:
            return TopicContinuationResult(
                TopicContinuationDecision.BRANCH_FROM_ORIGINAL,
                ("original_interest_remains", "direct_resume_score_low"),
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
