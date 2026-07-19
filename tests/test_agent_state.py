from app.domain.actions import ActionPlan, ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType
from app.runtime import AgentState


def test_agent_state_has_default_values() -> None:
    agent_state = AgentState()

    assert agent_state.active_activity is None
    assert agent_state.pending_activities == []
    assert agent_state.suspended_activities == []
    assert agent_state.running_actions == []
    assert agent_state.prepared_actions == []
    assert agent_state.current_drive == DriveState()
    assert agent_state.memory.episodic == ()
    assert agent_state.attention_target is None
    assert agent_state.stream_status == "idle"


def test_agent_state_can_update_active_activity() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話す",
    )

    agent_state = AgentState().with_active_activity(activity)

    assert agent_state.active_activity == activity


def test_agent_state_can_update_emotion() -> None:
    emotion = EmotionState(mood=MoodType.EXCITED, talkativeness=0.9)

    agent_state = AgentState().with_emotion(emotion)

    assert agent_state.current_emotion == emotion


def test_agent_state_can_update_drive() -> None:
    drive = DriveState(curiosity=0.9, engagement=0.8)

    agent_state = AgentState().with_drive(drive)

    assert agent_state.current_drive == drive


def test_agent_state_can_update_prepared_actions() -> None:
    action = ActionPlan(
        action_type=ActionType.SPEAK,
        text="次に話す内容",
    )

    agent_state = AgentState().with_prepared_actions([action])

    assert agent_state.prepared_actions == [action]


def test_agent_state_can_mark_user_input_received() -> None:
    agent_state = AgentState().mark_user_input_received()

    assert agent_state.last_user_input_at is not None


def test_agent_state_can_mark_speech_started() -> None:
    agent_state = AgentState().mark_speech_started()

    assert agent_state.last_speech_started_at is not None


def test_agent_state_can_mark_speech_finished() -> None:
    agent_state = AgentState().mark_speech_finished()

    assert agent_state.last_speech_finished_at is not None
