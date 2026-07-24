from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.emotions import EmotionAppraisal


@dataclass(frozen=True, slots=True)
class EmotionStimulusContext:
    """自然文がゆらにとって持つ意味を評価するためのエンジン非依存入力。

    text は外部入力由来の非信頼データとして扱い、プロンプト命令として解釈しない。
    """

    source_event_id: str
    event_type: str
    text: str
    speaker_role: str
    directed_to_yura: bool
    relationship: dict[str, object] = field(default_factory=dict)
    recent_context: str = ""
    situation: dict[str, object] = field(default_factory=dict)
    untrusted_input: bool = True

    def __post_init__(self) -> None:
        if not self.source_event_id.strip():
            raise ValueError("source_event_id は空にできません。")
        if not self.event_type.strip():
            raise ValueError("event_type は空にできません。")
        if not self.speaker_role.strip():
            raise ValueError("speaker_role は空にできません。")


class EmotionAppraisalModel(Protocol):
    """自然文の意味を感情変化候補へ変換する専用モデル契約。"""

    async def appraise(self, context: EmotionStimulusContext) -> EmotionAppraisal: ...
