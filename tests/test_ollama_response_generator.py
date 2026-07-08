

from __future__ import annotations

from typing import Any

import pytest

from app.adapters.llm import OllamaResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile


class FakeOllamaResponseGenerator(OllamaResponseGenerator):
    def __init__(self, response_data: dict[str, Any]) -> None:
        super().__init__(
            character_profile=_create_character_profile(),
            prompt_builder=SimplePromptBuilder(),
            model="test-model",
        )
        self.response_data = response_data
        self.sent_payload: dict[str, Any] | None = None

    def _post_generate_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.sent_payload = payload
        return self.response_data


class ErrorOllamaResponseGenerator(FakeOllamaResponseGenerator):
    def _post_generate_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.sent_payload = payload
        raise RuntimeError("Ollama API への接続に失敗しました。")


def _create_character_profile() -> CharacterProfile:
    return CharacterProfile(
        name="ミナト",
        personality="明るく好奇心が強い",
        speaking_style="親しみやすく、少しくだけた口調",
        streaming_style="視聴者と一緒に楽しむ雑談配信",
        likes=["海の生き物", "ゲーム"],
        dislikes=["攻撃的な話題"],
        behavior_policy=["短く自然に返答する"],
    )


def _create_conversation_activity() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={"event_payload": {"text": "こんにちは"}},
    )


@pytest.mark.asyncio
async def test_ollama_response_generator_returns_response_text() -> None:
    generator = FakeOllamaResponseGenerator(response_data={"response": "こんにちは、ミナトだよ！"})

    response = await generator.generate_response(_create_conversation_activity())

    assert response == "こんにちは、ミナトだよ！"


@pytest.mark.asyncio
async def test_ollama_response_generator_strips_response_text() -> None:
    generator = FakeOllamaResponseGenerator(response_data={"response": "  こんにちは！  \n"})

    response = await generator.generate_response(_create_conversation_activity())

    assert response == "こんにちは！"


@pytest.mark.asyncio
async def test_ollama_response_generator_keeps_latest_prompt() -> None:
    generator = FakeOllamaResponseGenerator(response_data={"response": "こんにちは！"})

    await generator.generate_response(_create_conversation_activity())

    assert generator.latest_prompt is not None
    assert "名前: ミナト" in generator.latest_prompt
    assert "こんにちは" in generator.latest_prompt


@pytest.mark.asyncio
async def test_ollama_response_generator_sends_expected_payload() -> None:
    generator = FakeOllamaResponseGenerator(response_data={"response": "こんにちは！"})

    await generator.generate_response(_create_conversation_activity())

    assert generator.sent_payload is not None
    assert generator.sent_payload["model"] == "test-model"
    assert generator.sent_payload["prompt"] == generator.latest_prompt
    assert generator.sent_payload["stream"] is False


@pytest.mark.asyncio
async def test_ollama_response_generator_returns_fallback_when_response_is_empty() -> None:
    generator = FakeOllamaResponseGenerator(response_data={"response": "   "})

    response = await generator.generate_response(_create_conversation_activity())

    assert response == "うまく言葉が出てこなかったみたい。もう一度話しかけてね。"


@pytest.mark.asyncio
async def test_ollama_response_generator_raises_runtime_error() -> None:
    generator = ErrorOllamaResponseGenerator(response_data={})

    with pytest.raises(RuntimeError, match="Ollama API への接続に失敗しました。"):
        await generator.generate_response(_create_conversation_activity())