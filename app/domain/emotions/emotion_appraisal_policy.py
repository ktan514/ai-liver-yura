from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from .emotion_appraisal import EmotionAppraisal


class EmotionAppraisalMode(str, Enum):
    """感情評価の実行方式。"""

    DISABLED = "disabled"
    RULE_BASED = "rule_based"
    LLM = "llm"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class EmotionAppraisalHistorySettings:
    max_entries: int = 200
    retention_seconds: float = 7200.0
    min_effective_delta: float = 0.02

    def __post_init__(self) -> None:
        if self.max_entries <= 0:
            raise ValueError("max_entries は1以上で指定してください。")
        if self.retention_seconds <= 0.0:
            raise ValueError("retention_seconds は0より大きく指定してください。")
        if not 0.0 <= self.min_effective_delta <= 1.0:
            raise ValueError("min_effective_delta は0.0以上1.0以下で指定してください。")


@dataclass(frozen=True, slots=True)
class EmotionAppraisalCircuitBreakerSettings:
    failure_threshold: int = 5
    recovery_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold は1以上で指定してください。")
        if self.recovery_seconds <= 0.0:
            raise ValueError("recovery_seconds は0より大きく指定してください。")


@dataclass(frozen=True, slots=True)
class EmotionAppraisalSettings:
    """Coreが参照する感情評価設定。Provider名やモデル名には依存しない。"""

    enabled: bool = True
    mode: EmotionAppraisalMode = EmotionAppraisalMode.HYBRID
    llm_role: str = "emotion_appraisal"
    timeout_seconds: float = 2.5
    confidence_threshold: float = 0.55
    weak_confidence_threshold: float = 0.40
    fallback: str = "rule_based"
    max_concurrency: int = 2
    cache_ttl_seconds: float = 20.0
    cache_max_entries: int = 256
    circuit_breaker: EmotionAppraisalCircuitBreakerSettings = field(
        default_factory=EmotionAppraisalCircuitBreakerSettings
    )
    history: EmotionAppraisalHistorySettings = field(
        default_factory=EmotionAppraisalHistorySettings
    )

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds は0より大きく指定してください。")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency は1以上で指定してください。")
        if self.cache_ttl_seconds <= 0.0 or self.cache_max_entries <= 0:
            raise ValueError("感情評価キャッシュ設定は正の値で指定してください。")
        if not 0.0 <= self.weak_confidence_threshold <= 1.0:
            raise ValueError("weak_confidence_threshold は0.0以上1.0以下で指定してください。")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold は0.0以上1.0以下で指定してください。")
        if self.weak_confidence_threshold > self.confidence_threshold:
            raise ValueError(
                "weak_confidence_threshold は confidence_threshold 以下にしてください。"
            )
        if not self.llm_role.strip():
            raise ValueError("llm_role は空文字にできません。")
        if self.fallback not in {"rule_based", "no_change"}:
            raise ValueError("fallback は rule_based または no_change を指定してください。")


class EmotionAppraisalAcceptancePolicy:
    """信頼度に応じて評価結果の影響量を安全に縮小する。"""

    def __init__(self, settings: EmotionAppraisalSettings | None = None) -> None:
        self._settings = settings or EmotionAppraisalSettings()

    def multiplier(self, confidence: float) -> float:
        confidence = max(0.0, min(1.0, confidence))
        if confidence < self._settings.weak_confidence_threshold:
            return 0.0
        if confidence < self._settings.confidence_threshold:
            return 0.35
        if confidence < 0.75:
            return 0.70
        return 1.0

    def apply(self, appraisal: EmotionAppraisal) -> EmotionAppraisal:
        factor = self.multiplier(appraisal.confidence)
        if factor == 1.0:
            return appraisal
        return replace(
            appraisal,
            joy_delta=appraisal.joy_delta * factor,
            amusement_delta=appraisal.amusement_delta * factor,
            anger_delta=appraisal.anger_delta * factor,
            sadness_delta=appraisal.sadness_delta * factor,
            fear_delta=appraisal.fear_delta * factor,
            surprise_delta=appraisal.surprise_delta * factor,
            discomfort_delta=appraisal.discomfort_delta * factor,
            pressure_delta=appraisal.pressure_delta * factor,
            arousal_delta=appraisal.arousal_delta * factor,
            valence_delta=appraisal.valence_delta * factor,
            talkativeness_delta=appraisal.talkativeness_delta * factor,
            reason=(
                appraisal.reason
                if factor > 0.0
                else f"rejected_low_confidence:{appraisal.reason}"
            ),
        )
