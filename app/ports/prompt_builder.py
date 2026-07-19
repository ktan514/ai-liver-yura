from __future__ import annotations

from typing import Protocol

from app.domain.activities import Activity
from app.domain.behavior import BehaviorPlanningContext
from app.domain.character import CharacterProfile
from app.domain.character_response import CharacterResponse, Claim, ResponseContext


class PromptBuilder(Protocol):
    """Activity と CharacterProfile から LLM 用 prompt を生成する Port。"""

    def build_prompt(
        self, activity: Activity, character_profile: CharacterProfile
    ) -> str: ...


class SituationPromptBuilder(Protocol):
    """Situation Evaluator向けの意味解析Promptを構築するPort。"""

    def build(self, context: BehaviorPlanningContext) -> str: ...


class CharacterRolePromptBuilder(Protocol):
    """確定済み事実をCharacter LLMへ渡すPromptを構築するPort。"""

    def build(
        self,
        context: ResponseContext,
        *,
        character_profile: CharacterProfile | None,
        correction: str | None,
    ) -> str: ...


class ResponseValidationPromptBuilder(Protocol):
    """Character Responseと実行事実の検証Promptを構築するPort。"""

    def build(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        extracted_claims: tuple[Claim, ...] = (),
    ) -> str: ...
