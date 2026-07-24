from datetime import datetime, timedelta, timezone

from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType
from app.domain.topic import (
    InterruptedTopic,
    TopicContinuationDecision,
    TopicLifecycleStatus,
)
from app.runtime.topic_continuation_evaluator import TopicContinuationEvaluator

NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


def _topic(**overrides: object) -> InterruptedTopic:
    values: dict[str, object] = {
        "topic_id": "topic-1",
        "source_activity_id": "activity-1",
        "original_text": "元の話題",
        "status": TopicLifecycleStatus.INTERRUPTED,
        "importance": 0.5,
        "interest": 0.5,
        "incompleteness": 0.5,
        "exhaustion": 0.1,
        "interrupted_at": NOW,
    }
    values.update(overrides)
    return InterruptedTopic(**values)  # type: ignore[arg-type]


def test_completed_low_importance_topic_is_not_resumed() -> None:
    result = TopicContinuationEvaluator().evaluate(
        _topic(importance=0.2, interest=0.2, incompleteness=0.05),
        emotion=EmotionState(),
        drive=DriveState(curiosity=0.9),
        now=NOW + timedelta(seconds=30),
    )

    assert result.decision != TopicContinuationDecision.RESUME_ORIGINAL
    assert result.decision == TopicContinuationDecision.START_NEW_TOPIC


def test_important_unfinished_topic_is_resumed_with_reintroduction() -> None:
    result = TopicContinuationEvaluator().evaluate(
        _topic(
            importance=0.9, interest=0.85, incompleteness=0.95, interruption_turns=1
        ),
        emotion=EmotionState(mood=MoodType.HAPPY, arousal=0.7, talkativeness=0.8),
        drive=DriveState(curiosity=0.8),
        now=NOW + timedelta(minutes=1),
    )

    assert result.decision == TopicContinuationDecision.RESUME_ORIGINAL
    assert result.reintroduction_required is True


def test_interruption_topic_can_be_selected_when_curiosity_is_high() -> None:
    result = TopicContinuationEvaluator().evaluate(
        _topic(
            original_text="海の生き物",
            importance=0.4,
            interest=0.5,
            incompleteness=0.3,
            interruption_turns=1,
            interruption_topics=("山の生き物",),
        ),
        emotion=EmotionState(mood=MoodType.EXCITED, arousal=0.8),
        drive=DriveState(curiosity=0.9),
        now=NOW + timedelta(minutes=2),
    )

    assert result.decision == TopicContinuationDecision.BRANCH_FROM_INTERRUPTION
    assert result.selected_topic == "山の生き物"


def test_angry_mood_does_not_mechanically_resume_cheerful_topic() -> None:
    result = TopicContinuationEvaluator().evaluate(
        _topic(importance=0.5, interest=0.8, incompleteness=0.6),
        emotion=EmotionState(mood=MoodType.ANGRY, valence=-0.8),
        drive=DriveState(curiosity=0.8),
        now=NOW + timedelta(minutes=1),
    )

    assert result.decision in {
        TopicContinuationDecision.WAIT,
        TopicContinuationDecision.SUSPEND_ORIGINAL,
    }


def test_suspended_topic_is_reframed_after_emotion_recovers() -> None:
    result = TopicContinuationEvaluator().evaluate(
        _topic(
            status=TopicLifecycleStatus.SUSPENDED,
            importance=0.85,
            interest=0.8,
            incompleteness=0.9,
            interruption_turns=2,
        ),
        emotion=EmotionState(mood=MoodType.NEUTRAL, valence=0.1, talkativeness=0.7),
        drive=DriveState(curiosity=0.8),
        now=NOW + timedelta(minutes=3),
    )

    assert result.decision == TopicContinuationDecision.RESUME_WITH_REFRAMING
    assert result.reintroduction_required is True


def test_exhausted_topic_is_not_resumed() -> None:
    result = TopicContinuationEvaluator().evaluate(
        _topic(importance=0.8, interest=0.6, incompleteness=0.6, exhaustion=0.9),
        emotion=EmotionState(),
        drive=DriveState(curiosity=0.8),
        now=NOW + timedelta(minutes=1),
    )

    assert result.decision == TopicContinuationDecision.ABANDON_ORIGINAL
