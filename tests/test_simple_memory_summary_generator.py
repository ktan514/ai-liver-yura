import pytest

from app.adapters.memory.simple_memory_summary_generator import (
    SimpleMemorySummaryGenerator,
    SimpleMemorySummaryGeneratorConfig,
)


@pytest.mark.asyncio
async def test_generate_summary_returns_short_text_as_is() -> None:
    generator = SimpleMemorySummaryGenerator()

    summary = await generator.generate_summary("クラゲの展示がきれいだった")

    assert summary == "クラゲの展示がきれいだった"


@pytest.mark.asyncio
async def test_generate_summary_normalizes_whitespace() -> None:
    generator = SimpleMemorySummaryGenerator()

    summary = await generator.generate_summary(
        "クラゲの展示が\n  とても   きれいだった"
    )

    assert summary == "クラゲの展示が とても きれいだった"


@pytest.mark.asyncio
async def test_generate_summary_truncates_long_text() -> None:
    generator = SimpleMemorySummaryGenerator(
        SimpleMemorySummaryGeneratorConfig(max_length=10)
    )

    summary = await generator.generate_summary("クラゲの展示がとてもきれいだった")

    assert summary == "クラゲの展示がとても..."
