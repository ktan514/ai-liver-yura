import pytest

from app.domain.emotions import EmotionState, MoodType
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy


def test_default_emotion_state_is_neutral() -> None:
    emotion_state = EmotionState()

    assert emotion_state.mood == MoodType.NEUTRAL
    assert emotion_state.arousal == 0.5
    assert emotion_state.valence == 0.0
    assert emotion_state.talkativeness == 0.5


def test_autonomous_policy_defers_talking_for_angry_emotion() -> None:
    emotion_state = EmotionState(mood=MoodType.ANGRY)
    policy = AutonomousActivityPolicy()

    assert policy.should_defer_talking(emotion_state)
    assert policy.minimum_talk_interval_seconds(emotion_state) == 5.0


def test_autonomous_policy_shortens_activity_interval_for_excited_emotion() -> None:
    emotion_state = EmotionState(mood=MoodType.EXCITED)
    policy = AutonomousActivityPolicy()

    assert not policy.should_defer_talking(emotion_state)
    assert policy.minimum_talk_interval_seconds(emotion_state) == 0.5
    assert policy.awakening_settle_seconds(emotion_state) >= 2.0


def test_low_talkativeness_reduces_speech() -> None:
    emotion_state = EmotionState(talkativeness=0.2)
    policy = AutonomousActivityPolicy()

    assert policy.should_defer_talking(emotion_state)
    assert policy.minimum_talk_interval_seconds(emotion_state) == 3.0


def test_invalid_arousal_raises_error() -> None:
    with pytest.raises(ValueError):
        EmotionState(arousal=1.1)


def test_invalid_valence_raises_error() -> None:
    with pytest.raises(ValueError):
        EmotionState(valence=-1.1)


def test_invalid_talkativeness_raises_error() -> None:
    with pytest.raises(ValueError):
        EmotionState(talkativeness=1.1)
