from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.adapters.tts.voicevox_voice_intent_mapper import VoiceVoxVoiceIntentMapper
from app.config.emotion_appraisal_config import load_emotion_appraisal_settings
from app.domain.emotions import (
    EmotionAppraisal,
    EmotionAppraisalAcceptancePolicy,
    EmotionAppraisalSettings,
    EmotionExpressionDeriver,
    EmotionState,
    PerformanceDirective,
    PerformanceDirectiveType,
    ReactiveEmotionState,
)
from app.domain.events import AgentEvent, AgentEventType
from app.domain.memory import AgentMemoryState, EmotionHistoryEntry
from app.runtime.emotion_appraisal_service import EmotionAppraisalService
from app.runtime.emotion_appraisal_validator import (
    EmotionAppraisalValidationError,
    EmotionAppraisalValidator,
)
from app.shared.contracts.expression import VoiceIntent


def test_low_confidence_appraisal_does_not_change_emotion() -> None:
    policy = EmotionAppraisalAcceptancePolicy(
        EmotionAppraisalSettings(
            weak_confidence_threshold=0.4,
            confidence_threshold=0.55,
        )
    )

    accepted = policy.apply(
        EmotionAppraisal(
            anger_delta=0.8,
            valence_delta=-0.7,
            confidence=0.2,
            reason="ambiguous_text",
        )
    )

    assert accepted.anger_delta == 0.0
    assert accepted.valence_delta == 0.0
    assert accepted.reason == "rejected_low_confidence:ambiguous_text"


def test_emotion_expression_deriver_preserves_mixed_emotions() -> None:
    expression = EmotionExpressionDeriver().derive(
        EmotionState(
            arousal=0.75,
            valence=-0.35,
            reactive=ReactiveEmotionState(
                anger=0.7,
                sadness=0.45,
                discomfort=0.3,
                emotional_pressure=0.6,
            ),
        )
    )

    assert expression.primary == "anger"
    assert expression.secondary == "sadness"
    assert expression.tension == pytest.approx(0.7)
    assert expression.expressivity > 0.5


def test_performance_directive_is_independent_from_internal_emotion() -> None:
    directive = PerformanceDirective(
        directive_type=PerformanceDirectiveType.ACT_SAD,
        intensity=0.8,
        source="user_request",
    )
    state = EmotionState()

    assert directive.directive_type == PerformanceDirectiveType.ACT_SAD
    assert directive.intensity == 0.8
    assert state.reactive.sadness == 0.0


def test_emotion_history_discards_stale_and_tiny_changes() -> None:
    now = datetime.now(timezone.utc)
    state = AgentMemoryState(
        max_history_entries=3,
        emotion_history_retention_seconds=60.0,
        emotion_history_min_effective_delta=0.05,
        emotion_history=(
            EmotionHistoryEntry(
                source_event_id="old",
                before={"reactive": {"anger": 0.0}},
                after={"reactive": {"anger": 0.8}},
                reason="old_event",
                recorded_at=now - timedelta(minutes=5),
            ),
        ),
    )

    unchanged = state.record_emotion(
        EmotionHistoryEntry(
            source_event_id="tiny",
            before={"reactive": {"anger": 0.0}},
            after={"reactive": {"anger": 0.01}},
            reason="tiny_event",
            recorded_at=now,
        )
    )
    changed = unchanged.record_emotion(
        EmotionHistoryEntry(
            source_event_id="effective",
            before={"reactive": {"anger": 0.0}},
            after={"reactive": {"anger": 0.4}},
            reason="effective_event",
            recorded_at=now,
        )
    )

    assert [entry.source_event_id for entry in changed.emotion_history] == ["effective"]


def test_voicevox_mapper_clamps_extreme_voice_intent() -> None:
    speed, pitch, intonation, volume = VoiceVoxVoiceIntentMapper().map(
        base_speed=1.5,
        base_pitch=0.14,
        base_intonation=1.8,
        base_volume=1.8,
        intent=VoiceIntent(
            style="excited",
            speed=2.0,
            pitch=1.0,
            intonation=2.0,
            volume=2.0,
            emotional_leakage=1.0,
        ),
    )

    assert speed == 2.0
    assert pitch == 0.15
    assert intonation == 2.0
    assert volume == 2.0


def test_emotion_appraisal_validator_rejects_out_of_range_delta() -> None:
    with pytest.raises(EmotionAppraisalValidationError):
        EmotionAppraisalValidator().validate(
            EmotionAppraisal(anger_delta=1.5, confidence=0.8)
        )


def test_empty_config_path_uses_emotion_appraisal_defaults() -> None:
    settings = load_emotion_appraisal_settings("")

    assert settings.enabled is True
    assert settings.timeout_seconds == pytest.approx(2.5)


class _SlowAppraisalModel:
    async def appraise(self, context: object) -> EmotionAppraisal:
        await asyncio.sleep(0.05)
        return EmotionAppraisal(joy_delta=0.5, confidence=0.9)


@pytest.mark.asyncio
async def test_emotion_appraisal_timeout_falls_back_without_blocking() -> None:
    service = EmotionAppraisalService(
        _SlowAppraisalModel(),
        settings=EmotionAppraisalSettings(
            timeout_seconds=0.001,
            fallback="rule_based",
        ),
    )
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
    )

    enriched = await service.enrich(event)

    structured = enriched.payload["emotion_appraisal"]
    assert isinstance(structured, dict)
    assert str(structured["source"]).startswith("fallback:timeout")
    assert service.metrics["timeout"] == 1
    assert service.metrics["fallback_used"] == 1


@pytest.mark.asyncio
async def test_acting_request_skips_internal_emotion_appraisal() -> None:
    service = EmotionAppraisalService(
        _SlowAppraisalModel(),
        settings=EmotionAppraisalSettings(timeout_seconds=0.1),
    )
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "悲しそうに読んで", "emotion_mode": "acting"},
    )

    enriched = await service.enrich(event)

    assert enriched.payload["emotion_appraisal_skipped"] == "performance_request"
    assert "emotion_appraisal" not in enriched.payload
