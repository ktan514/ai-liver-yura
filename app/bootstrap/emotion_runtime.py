from __future__ import annotations

from app.adapters.llm.response_generator_emotion_appraisal_model import (
    ResponseGeneratorEmotionAppraisalModel,
)
from app.adapters.prompt import SimplePromptBuilder
from app.bootstrap.runtime import (
    create_character_profile,
    create_response_generator,
    create_runtime_coordinator as create_base_runtime_coordinator,
)
from app.config.app_config import AppConfig
from app.config.emotion_appraisal_config import load_emotion_appraisal_settings
from app.domain.emotions import EmotionAppraisalMode
from app.runtime.emotion_appraisal_service import EmotionAppraisalService
from app.runtime.emotion_runtime_integration import (
    EmotionAwareRuntimeCoordinator,
    attach_emotion_runtime,
)


def create_runtime_coordinator(config: AppConfig) -> EmotionAwareRuntimeCoordinator:
    """標準Runtimeへ自然文感情評価を明示的な依存として合成する。"""

    coordinator = create_base_runtime_coordinator(config)
    settings = load_emotion_appraisal_settings(config.config_path)
    model = None
    if settings.enabled and settings.mode in {
        EmotionAppraisalMode.LLM,
        EmotionAppraisalMode.HYBRID,
    }:
        character_profile = create_character_profile(config)
        appraisal_generator = create_response_generator(
            config=config,
            character_profile=character_profile,
            prompt_builder=SimplePromptBuilder(),
            temperature=0.0,
        )
        model = ResponseGeneratorEmotionAppraisalModel(appraisal_generator)
    return attach_emotion_runtime(
        coordinator,
        EmotionAppraisalService(
            model,
            settings=settings,
        ),
    )
