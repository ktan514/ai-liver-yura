

from __future__ import annotations

from typing import Protocol


class EmbeddingGenerator(Protocol):
    async def generate_embedding(self, text: str) -> list[float]:
        raise NotImplementedError