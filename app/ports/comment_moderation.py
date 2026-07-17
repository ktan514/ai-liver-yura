from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SemanticModerationResult:
    status: str
    safety_category: str
    severity: str
    confidence: float
    reason_codes: tuple[str, ...] = ()


class CommentSemanticModerationPort(Protocol):
    async def evaluate(self, quoted_external_text: str) -> SemanticModerationResult: ...
