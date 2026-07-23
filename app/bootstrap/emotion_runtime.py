from __future__ import annotations

from typing import Any

from app.adapters.llm.response_generator_emotion_appraisal_model import (
    ResponseGeneratorEmotionAppraisalModel,
)
from app.bootstrap.runtime import create_runtime_coordinator as create_base_runtime_coordinator
from app.config.app_config import AppConfig
from app.runtime.emotion_appraisal_service import EmotionAppraisalService
from app.runtime.emotion_runtime_integration import attach_emotion_runtime
from app.runtime.runtime_coordinator import RuntimeCoordinator


def create_runtime_coordinator(config: AppConfig) -> RuntimeCoordinator:
    """標準Runtimeへ自然文感情評価と感情文脈生成を組み込む。"""

    coordinator = create_base_runtime_coordinator(config)
    generator = _response_generator_from(coordinator)
    if generator is None:
        return coordinator
    model = ResponseGeneratorEmotionAppraisalModel(generator)
    return attach_emotion_runtime(
        coordinator,
        EmotionAppraisalService(model),
    )


def _response_generator_from(coordinator: RuntimeCoordinator) -> Any | None:
    action_planner = getattr(coordinator, "_action_planner", None)
    return getattr(action_planner, "_response_generator", None)
