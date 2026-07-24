from __future__ import annotations

from dataclasses import dataclass

from app.ports.memory_summary_generator import MemorySummaryGenerator


@dataclass(frozen=True)
class SimpleMemorySummaryGeneratorConfig:
    max_length: int = 120


class SimpleMemorySummaryGenerator(MemorySummaryGenerator):
    def __init__(
        self, config: SimpleMemorySummaryGeneratorConfig | None = None
    ) -> None:
        self._config = config or SimpleMemorySummaryGeneratorConfig()

    async def generate_summary(self, text: str) -> str:
        normalized_text = " ".join(text.split())
        if len(normalized_text) <= self._config.max_length:
            return normalized_text

        return normalized_text[: self._config.max_length].rstrip() + "..."
