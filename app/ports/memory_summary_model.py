from __future__ import annotations

from typing import Protocol


class MemorySummaryModel(Protocol):
    async def generate_memory_summary(self, prompt: str) -> str:
        raise NotImplementedError
