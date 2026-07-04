

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CharacterProfile:
    """AIライバーの人格・口調・配信スタイルを保持するドメインモデル。"""

    name: str
    personality: str
    speaking_style: str
    streaming_style: str
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    behavior_policy: list[str] = field(default_factory=list)