

from __future__ import annotations

from dataclasses import dataclass

from app.ports.memory_summary_generator import MemorySummaryGenerator
from app.ports.memory_summary_model import MemorySummaryModel


@dataclass(frozen=True)
class LlmMemorySummaryGeneratorConfig:
    fallback_max_length: int = 120


class LlmMemorySummaryGenerator(MemorySummaryGenerator):
    """LLM を使って長期記憶向けの検索しやすい1文要約を生成する。"""

    def __init__(
        self,
        model: MemorySummaryModel,
        config: LlmMemorySummaryGeneratorConfig | None = None,
    ) -> None:
        self._model = model
        self._config = config or LlmMemorySummaryGeneratorConfig()

    async def generate_summary(self, text: str) -> str:
        normalized_text = " ".join(text.split())
        if not normalized_text:
            return ""

        prompt = self._build_prompt(normalized_text)
        summary = await self._model.generate_memory_summary(prompt)
        normalized_summary = " ".join(summary.split())
        if normalized_summary:
            return normalized_summary

        return self._fallback_summary(normalized_text)

    def _build_prompt(self, text: str) -> str:
        return "\n".join(
            [
                "あなたはAIキャラクターの長期記憶を作る要約器です。",
                "次の発話を、後から検索しやすい1文の記憶に変換してください。",
                "",
                "# 条件",
                "- 40〜80文字程度",
                "- 会話口調を避ける",
                "- 「〜だよね」「〜かな」などは使わない",
                "- キャラクターの関心・話題・印象が分かる文にする",
                "- 新しい事実を追加しない",
                "- 出力は要約文のみ",
                "",
                "# 発話",
                text,
            ]
        )

    def _fallback_summary(self, text: str) -> str:
        if len(text) <= self._config.fallback_max_length:
            return text

        return text[: self._config.fallback_max_length].rstrip() + "..."