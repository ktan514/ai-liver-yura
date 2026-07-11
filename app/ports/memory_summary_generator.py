from __future__ import annotations

from typing import Protocol


class MemorySummaryGenerator(Protocol):
    async def generate_summary(self, text: str) -> str:
        raise NotImplementedError
