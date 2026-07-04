

from __future__ import annotations

from typing import Protocol

from app.domain.activities import Activity
from app.domain.character import CharacterProfile


class PromptBuilder(Protocol):
    """Activity と CharacterProfile から LLM 用 prompt を生成する Port。"""

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        ...