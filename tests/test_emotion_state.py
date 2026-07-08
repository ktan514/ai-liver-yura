import pytest

from app.domain.emotions import EmotionState, MoodType


def test_default_emotion_state_is_neutral() -> None:
    emotion_state = EmotionState()

    assert emotion_state.mood == MoodType.NEUTRAL
    assert emotion_state.arousal == 0.5
    assert emotion_state.valence == 0.0
    assert emotion_state.talkativeness == 0.5


def test_angry_emotion_reduces_speech() -> None:
    emotion_state = EmotionState(mood=MoodType.ANGRY)

    assert emotion_state.should_reduce_speech()
    assert emotion_state.speech_pause_seconds() == 5.0


def test_excited_emotion_increases_reaction() -> None:
    emotion_state = EmotionState(mood=MoodType.EXCITED)

    assert emotion_state.should_increase_reaction()
    assert emotion_state.speech_pause_seconds() == 0.5


def test_low_talkativeness_reduces_speech() -> None:
    emotion_state = EmotionState(talkativeness=0.2)

    assert emotion_state.should_reduce_speech()
    assert emotion_state.speech_pause_seconds() == 3.0


def test_invalid_arousal_raises_error() -> None:
    with pytest.raises(ValueError):
        EmotionState(arousal=1.1)


def test_invalid_valence_raises_error() -> None:
    with pytest.raises(ValueError):
        EmotionState(valence=-1.1)


def test_invalid_talkativeness_raises_error() -> None:
    with pytest.raises(ValueError):
        EmotionState(talkativeness=1.1)