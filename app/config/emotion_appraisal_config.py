from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.domain.emotions import (
    EmotionAppraisalCircuitBreakerSettings,
    EmotionAppraisalHistorySettings,
    EmotionAppraisalMode,
    EmotionAppraisalSettings,
)


def load_emotion_appraisal_settings(
    config_path: str | Path,
) -> EmotionAppraisalSettings:
    """config.yamlのemotion_appraisalを型付き設定へ変換する。"""

    path = Path(config_path)
    if not path.exists():
        return EmotionAppraisalSettings()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("設定ファイルのルートはmappingである必要があります。")
    section = raw.get("emotion_appraisal", {})
    if section is None:
        section = {}
    if not isinstance(section, dict):
        raise ValueError("emotion_appraisalはmappingで指定してください。")
    circuit = _mapping(section.get("circuit_breaker"), "circuit_breaker")
    history = _mapping(section.get("history"), "history")
    enabled = _boolean(section.get("enabled"), True)
    configured_mode = str(section.get("mode") or "hybrid")
    mode = EmotionAppraisalMode(configured_mode)
    if not enabled:
        mode = EmotionAppraisalMode.DISABLED
    return EmotionAppraisalSettings(
        enabled=enabled,
        mode=mode,
        llm_role=str(section.get("llm_role") or "emotion_appraisal"),
        timeout_seconds=_number(section.get("timeout_seconds"), 2.5),
        confidence_threshold=_number(
            section.get("confidence_threshold"), 0.55
        ),
        weak_confidence_threshold=_number(
            section.get("weak_confidence_threshold"), 0.40
        ),
        fallback=str(section.get("fallback") or "rule_based"),
        max_concurrency=_integer(section.get("max_concurrency"), 2),
        cache_ttl_seconds=_number(section.get("cache_ttl_seconds"), 20.0),
        cache_max_entries=_integer(section.get("cache_max_entries"), 256),
        circuit_breaker=EmotionAppraisalCircuitBreakerSettings(
            failure_threshold=_integer(circuit.get("failure_threshold"), 5),
            recovery_seconds=_number(circuit.get("recovery_seconds"), 30.0),
        ),
        history=EmotionAppraisalHistorySettings(
            max_entries=_integer(history.get("max_entries"), 200),
            retention_seconds=_number(history.get("retention_seconds"), 7200.0),
            min_effective_delta=_number(
                history.get("min_effective_delta"), 0.02
            ),
        ),
    )


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"emotion_appraisal.{name}はmappingで指定してください。")
    return value


def _boolean(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError("boolean設定にはtrue/falseを指定してください。")
    return value


def _number(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("数値設定にはnumberを指定してください。")
    return float(value)


def _integer(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("整数設定にはintegerを指定してください。")
    return value
