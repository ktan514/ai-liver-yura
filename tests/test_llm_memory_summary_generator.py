

import pytest

from app.adapters.memory.llm_memory_summary_generator import (
    LlmMemorySummaryGenerator,
    LlmMemorySummaryGeneratorConfig,
)


class FakeMemorySummaryModel:
    def __init__(self, summary: str) -> None:
        self.summary = summary
        self.received_prompts: list[str] = []

    async def generate_memory_summary(self, prompt: str) -> str:
        self.received_prompts.append(prompt)
        return self.summary


@pytest.mark.asyncio
async def test_generate_summary_uses_model_response() -> None:
    model = FakeMemorySummaryModel(summary="イルカのジャンプの軽やかさに興味を示した")
    generator = LlmMemorySummaryGenerator(model=model)

    summary = await generator.generate_summary(
        "海で見たイルカのジャンプを思い出してたんだ。あの軽やかさって、何度見ても飽きないなあ。"
    )

    assert summary == "イルカのジャンプの軽やかさに興味を示した"
    assert len(model.received_prompts) == 1
    assert "あなたはAIキャラクターの長期記憶を作る要約器です。" in model.received_prompts[0]
    assert "# 条件" in model.received_prompts[0]
    assert "# 発話" in model.received_prompts[0]
    assert (
        "海で見たイルカのジャンプを思い出してたんだ。"
        "あの軽やかさって、何度見ても飽きないなあ。" in model.received_prompts[0]
    )


@pytest.mark.asyncio
async def test_generate_summary_normalizes_input_and_model_response_whitespace() -> None:
    model = FakeMemorySummaryModel(
        summary="  水面に反射する光や波の変化に\n関心を持った  "
    )
    generator = LlmMemorySummaryGenerator(model=model)

    summary = await generator.generate_summary("水面に\n\nキラキラ   反射する光が気になる")

    assert summary == "水面に反射する光や波の変化に 関心を持った"
    assert "水面に キラキラ 反射する光が気になる" in model.received_prompts[0]


@pytest.mark.asyncio
async def test_generate_summary_returns_empty_string_without_calling_model_when_text_is_blank(
) -> None:
    model = FakeMemorySummaryModel(summary="呼ばれない")
    generator = LlmMemorySummaryGenerator(model=model)

    summary = await generator.generate_summary("   \n\t   ")

    assert summary == ""
    assert model.received_prompts == []


@pytest.mark.asyncio
async def test_generate_summary_falls_back_to_original_text_when_model_response_is_blank() -> None:
    model = FakeMemorySummaryModel(summary="   ")
    generator = LlmMemorySummaryGenerator(
        model=model,
        config=LlmMemorySummaryGeneratorConfig(fallback_max_length=10),
    )

    summary = await generator.generate_summary("クラゲの展示がとてもきれいだった")

    assert summary == "クラゲの展示がとても..."
    assert len(model.received_prompts) == 1
