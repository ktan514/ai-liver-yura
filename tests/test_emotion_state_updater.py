from datetime import datetime, timedelta, timezone

import pytest

from app.domain.emotions import EmotionAppraisal, EmotionState, MoodType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime import ActivityManager, AgentLifeService
from app.runtime.emotion_appraiser import EmotionAppraiser
from app.runtime.emotion_state_updater import EmotionStateUpdater


def test_emotion_state_updater_applies_deltas_with_range_guarantees() -> None:
    state = EmotionState(arousal=0.98, valence=-0.97, talkativeness=0.99)

    updated = EmotionStateUpdater().apply(
        state,
        EmotionAppraisal(
            arousal_delta=0.2,
            valence_delta=-0.2,
            talkativeness_delta=0.2,
            reason="test",
        ),
    )

    assert updated.arousal == 1.0
    assert updated.valence == -1.0
    assert updated.talkativeness == 1.0


def test_emotion_state_updater_decays_toward_baseline_and_preserves_mood_until_settled() -> (
    None
):
    updater = EmotionStateUpdater()
    state = EmotionState(
        mood=MoodType.EXCITED,
        arousal=1.0,
        valence=0.8,
        talkativeness=0.9,
    )

    halfway = updater.decay(state, elapsed_seconds=900.0)
    settled = updater.decay(state, elapsed_seconds=1800.0)

    assert halfway == EmotionState(
        mood=MoodType.EXCITED,
        arousal=0.75,
        valence=0.4,
        talkativeness=0.7,
    )
    assert settled == EmotionState()


def test_emotion_appraiser_uses_event_fact_without_inferring_user_sentiment() -> None:
    appraisal = EmotionAppraiser().appraise(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "最悪だし腹が立つ"},
        )
    )

    assert appraisal.reason == "user_attention_received"
    assert appraisal.valence_delta == 0.0
    assert appraisal.arousal_delta > 0.0


def test_agent_life_service_applies_event_appraisal_and_elapsed_decay() -> None:
    started_at = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    service = AgentLifeService(ActivityManager(), now=started_at)
    event = AgentEvent(
        event_type=AgentEventType.ACTION_FAILED,
        occurred_at=started_at,
    )

    after_event = service.handle_event(event).current_emotion
    service.plan_next_event(now=started_at + timedelta(minutes=30))
    after_decay = service.agent_state.current_emotion

    assert after_event.arousal == pytest.approx(0.58)
    assert after_event.valence == pytest.approx(-0.08)
    assert after_event.talkativeness == pytest.approx(0.48)
    assert after_decay == EmotionState()
