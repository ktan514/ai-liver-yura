from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import asdict, replace
from time import monotonic

from app.domain.emotions import (
    EmotionAppraisal,
    EmotionAppraisalMode,
    EmotionAppraisalSettings,
)
from app.domain.events import AgentEvent, AgentEventType
from app.ports.emotion_appraisal_model import (
    EmotionAppraisalModel,
    EmotionStimulusContext,
)
from app.runtime.emotion_appraisal_validator import EmotionAppraisalValidator
from app.runtime.emotion_appraiser import EmotionAppraiser
from app.utils.trace import TraceLogger


class EmotionAppraisalService:
    """自然文の意味評価を実行し、構造化結果をEventへ付与する。"""

    _TEXT_EVENTS = {
        AgentEventType.USER_TEXT,
        AgentEventType.USER_SPEECH,
        AgentEventType.YOUTUBE_COMMENT,
    }
    _PERFORMANCE_REQUEST_KINDS = {
        "emotion_performance",
        "acting_request",
        "style_instruction",
    }

    def __init__(
        self,
        model: EmotionAppraisalModel | None,
        *,
        settings: EmotionAppraisalSettings | None = None,
        fallback_appraiser: EmotionAppraiser | None = None,
        validator: EmotionAppraisalValidator | None = None,
    ) -> None:
        self._model = model
        self._settings = settings or EmotionAppraisalSettings()
        self._fallback_appraiser = fallback_appraiser or EmotionAppraiser()
        self._validator = validator or EmotionAppraisalValidator()
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrency)
        self._cache: OrderedDict[str, tuple[float, EmotionAppraisal]] = OrderedDict()
        self._failure_count = 0
        self._breaker_open_until = 0.0
        self._trace_logger = TraceLogger()
        self._metrics = {
            "requested": 0,
            "llm_succeeded": 0,
            "fallback_used": 0,
            "cache_hit": 0,
            "timeout": 0,
            "failed": 0,
            "skipped": 0,
            "breaker_open": 0,
        }

    @property
    def metrics(self) -> dict[str, int]:
        return dict(self._metrics)

    async def enrich(
        self,
        event: AgentEvent,
        *,
        relationship: dict[str, object] | None = None,
        situation: dict[str, object] | None = None,
        recent_context: str = "",
        request_kind: str | None = None,
    ) -> AgentEvent:
        self._metrics["requested"] += 1
        skip_reason = self._skip_reason(event, request_kind=request_kind)
        if skip_reason is not None:
            self._metrics["skipped"] += 1
            return replace(
                event,
                payload={
                    **event.payload,
                    "emotion_appraisal_skipped": skip_reason,
                },
            )

        if self._settings.mode == EmotionAppraisalMode.RULE_BASED:
            return self._attach(event, self._fallback(event), source="rule_based")

        text = self._event_text(event)
        cache_key = self._cache_key(event, text)
        cached = self._cached(cache_key)
        if cached is not None:
            self._metrics["cache_hit"] += 1
            return self._attach(event, cached, source="cache")

        if self._model is None or self._breaker_is_open():
            if self._breaker_is_open():
                self._metrics["breaker_open"] += 1
            return self._attach_fallback(event, reason="model_unavailable")

        context = EmotionStimulusContext(
            source_event_id=event.event_id,
            event_type=event.event_type.value,
            text=text,
            speaker_role=event.authority.role,
            directed_to_yura=self._directed_to_yura(event),
            relationship=dict(relationship or {}),
            recent_context=recent_context,
            situation=dict(situation or {}),
            untrusted_input=True,
        )
        try:
            async with self._semaphore:
                appraisal = await asyncio.wait_for(
                    self._model.appraise(context),
                    timeout=self._settings.timeout_seconds,
                )
            validated = self._validator.validate(appraisal)
        except asyncio.TimeoutError:
            self._metrics["timeout"] += 1
            self._record_failure("timeout", event)
            return self._attach_fallback(event, reason="timeout")
        except Exception as error:
            self._metrics["failed"] += 1
            self._record_failure(type(error).__name__, event)
            return self._attach_fallback(event, reason=type(error).__name__)

        self._record_success()
        self._metrics["llm_succeeded"] += 1
        self._put_cache(cache_key, validated)
        return self._attach(event, validated, source="llm")

    def _skip_reason(
        self,
        event: AgentEvent,
        *,
        request_kind: str | None,
    ) -> str | None:
        if not self._settings.enabled or self._settings.mode == EmotionAppraisalMode.DISABLED:
            return "disabled"
        if event.event_type not in self._TEXT_EVENTS:
            return "unsupported_event"
        if self._is_performance_request(event, request_kind=request_kind):
            return "performance_request"
        if not self._event_text(event):
            return "empty_text"
        return None

    def _attach_fallback(self, event: AgentEvent, *, reason: str) -> AgentEvent:
        self._metrics["fallback_used"] += 1
        if self._settings.fallback == "no_change":
            appraisal = EmotionAppraisal(
                reason=f"fallback_no_change:{reason}",
                source_event_id=event.event_id,
            )
        else:
            appraisal = self._fallback(event)
        return self._attach(event, appraisal, source=f"fallback:{reason}")

    def _fallback(self, event: AgentEvent) -> EmotionAppraisal:
        return self._validator.validate(self._fallback_appraiser.appraise(event))

    def _attach(
        self,
        event: AgentEvent,
        appraisal: EmotionAppraisal,
        *,
        source: str,
    ) -> AgentEvent:
        cause = asdict(appraisal.cause) if appraisal.cause is not None else None
        structured = {
            "joy_delta": appraisal.joy_delta,
            "amusement_delta": appraisal.amusement_delta,
            "anger_delta": appraisal.anger_delta,
            "sadness_delta": appraisal.sadness_delta,
            "fear_delta": appraisal.fear_delta,
            "surprise_delta": appraisal.surprise_delta,
            "discomfort_delta": appraisal.discomfort_delta,
            "pressure_delta": appraisal.pressure_delta,
            "arousal_delta": appraisal.arousal_delta,
            "valence_delta": appraisal.valence_delta,
            "talkativeness_delta": appraisal.talkativeness_delta,
            "reason": appraisal.reason,
            "cause": cause,
            "confidence": appraisal.confidence,
            "source": source,
        }
        return replace(
            event,
            payload={
                **event.payload,
                "emotion_appraisal": structured,
            },
        )

    def _breaker_is_open(self) -> bool:
        return monotonic() < self._breaker_open_until

    def _record_failure(self, reason: str, event: AgentEvent) -> None:
        self._failure_count += 1
        if self._failure_count >= self._settings.circuit_breaker.failure_threshold:
            self._breaker_open_until = (
                monotonic() + self._settings.circuit_breaker.recovery_seconds
            )
            self._failure_count = 0
        self._trace_logger.warning(
            "emotion_appraisal_service:evaluation_failed",
            source_event_id=event.event_id,
            event_type=event.event_type.value,
            reason=reason,
            breaker_open=self._breaker_is_open(),
        )

    def _record_success(self) -> None:
        self._failure_count = 0
        self._breaker_open_until = 0.0

    def _cached(self, key: str) -> EmotionAppraisal | None:
        item = self._cache.get(key)
        if item is None:
            return None
        stored_at, appraisal = item
        if monotonic() - stored_at > self._settings.cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return appraisal

    def _put_cache(self, key: str, appraisal: EmotionAppraisal) -> None:
        self._cache[key] = (monotonic(), appraisal)
        self._cache.move_to_end(key)
        while len(self._cache) > self._settings.cache_max_entries:
            self._cache.popitem(last=False)

    @staticmethod
    def _cache_key(event: AgentEvent, text: str) -> str:
        return "|".join(
            (
                event.event_type.value,
                event.authority.role,
                "1" if EmotionAppraisalService._directed_to_yura(event) else "0",
                " ".join(text.split()).casefold(),
            )
        )

    @classmethod
    def _is_performance_request(
        cls, event: AgentEvent, *, request_kind: str | None
    ) -> bool:
        if request_kind in cls._PERFORMANCE_REQUEST_KINDS:
            return True
        value = event.payload.get("emotion_mode")
        return isinstance(value, str) and value in {"performance", "acting"}

    @staticmethod
    def _event_text(event: AgentEvent) -> str:
        value = event.payload.get("text") or event.payload.get("comment")
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _directed_to_yura(event: AgentEvent) -> bool:
        value = event.payload.get("directed_to_yura")
        if isinstance(value, bool):
            return value
        return event.event_type in {
            AgentEventType.USER_TEXT,
            AgentEventType.USER_SPEECH,
        }
