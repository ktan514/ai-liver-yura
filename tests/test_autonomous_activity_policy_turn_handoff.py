from app.domain.emotions import EmotionState, MoodType
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy


def test_default_state_keeps_long_turn_handoff() -> None:
    policy = AutonomousActivityPolicy()

    assert policy.minimum_talk_interval_seconds(EmotionState()) == 45.0


def test_excited_state_still_keeps_listener_entry_window() -> None:
    policy = AutonomousActivityPolicy()
    emotion = EmotionState(mood=MoodType.EXCITED, talkativeness=0.9)

    assert policy.minimum_talk_interval_seconds(emotion) == 20.0


def test_tired_state_prefers_silence() -> None:
    policy = AutonomousActivityPolicy()
    emotion = EmotionState(mood=MoodType.TIRED, talkativeness=0.2)

    assert policy.minimum_talk_interval_seconds(emotion) == 60.0
