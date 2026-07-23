from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.emotions import EmotionAppraisal


@dataclass(frozen=True, slots=True)
class EmotionStimulusContext:
    """自然文がゆらにとって持つ意味を評価するためのエンジン非依存入力。"""

    source_event_id: str
    event_type: str
    text: str
    speaker_role: str
    directed_to_yura: bool
    relationship: dict[str, object] = field(default_factory=dict)
    recent_context: str = ""
    situation: dict[str, object] = field(default_factory=dict)


class EmotionAppraisalModel(Protocol):
    """自然文の意味を感情変化候補へ変換する専用モデル契約。"""

    async def appraise(self, context: EmotionStimulusContext) -> EmotionAppraisal: ...
