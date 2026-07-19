from __future__ import annotations

import pytest

from app.plugins.games.engine import GameEngine
from app.plugins.games.intent import (
    GameIntent,
    GameIntentCommandParser,
    GameIntentInterpreter,
)
from app.plugins.games.shiritori.domain import ShiritoriGameDefinition
from app.shared.contracts.plugins.runtime import PluginLlmRequest


class StaticLlm:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    async def generate_response(self, request: PluginLlmRequest) -> str:
        self.calls += 1
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    ["しりとりしよう", "しりとりしよ", "しりとりしたい", "しりとりやろう"],
)
async def test_safe_start_shortcuts_do_not_call_llm(text: str) -> None:
    llm = StaticLlm("invalid")
    interpreter = GameIntentInterpreter(
        GameEngine((ShiritoriGameDefinition(),)),
        llm,
    )

    command = await interpreter.interpret(text, state_version=0)

    assert command.intent == GameIntent.START_GAME
    assert command.game_type == "shiritori"
    assert llm.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "しりとりって知ってる？",
        "しりとり得意？",
        "しりとりのルール教えて",
        "昨日しりとりした",
        "しりとりはやりたくない",
        "しりとりで負けた",
    ],
)
async def test_negative_question_and_past_references_do_not_start(text: str) -> None:
    llm = StaticLlm("invalid")
    interpreter = GameIntentInterpreter(
        GameEngine((ShiritoriGameDefinition(),)),
        llm,
    )

    command = await interpreter.interpret(text, state_version=0)

    assert command.intent == GameIntent.NORMAL_CHAT
    assert llm.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "しりとりやらない？",
        "しりとり付き合って",
        "しりとりでもする？",
        "じゃあしりとりね",
        "何か遊ぼうよ、しりとりとか",
        "久しぶりに言葉遊びしない？",
    ],
)
async def test_natural_start_expression_is_resolved_by_llm(text: str) -> None:
    llm = StaticLlm(
        '{"intent":"start_game","game_type":"shiritori","confidence":0.97,'
        '"game_move":null,"chat_text":null,"control":null,'
        '"requires_confirmation":false,"reason":"semantic_start","state_version":4}'
    )
    interpreter = GameIntentInterpreter(
        GameEngine((ShiritoriGameDefinition(),)),
        llm,
    )

    command = await interpreter.interpret(text, state_version=4)

    assert command.intent == GameIntent.START_GAME
    assert command.classifier_type == "llm"
    assert llm.calls == 1


@pytest.mark.parametrize(
    "raw",
    [
        '説明です {"intent":"normal_chat"}',
        '{"intent":"unknown","confidence":1,"state_version":1,'
        '"requires_confirmation":false,"reason":"x"}',
        '{"intent":"start_game","game_type":"shiritori","confidence":1.2,'
        '"state_version":1,"requires_confirmation":false,"reason":"x"}',
        '{"intent":"play_game_move","game_type":"shiritori","confidence":1,'
        '"state_version":1,"requires_confirmation":false,"reason":"x"}',
        '{"intent":"normal_chat","game_type":null,"confidence":1,'
        '"state_version":2,"requires_confirmation":false,"reason":"x"}',
    ],
)
def test_parser_rejects_invalid_structured_output(raw: str) -> None:
    parser = GameIntentCommandParser(frozenset({"shiritori"}))

    assert parser.parse(raw, expected_state_version=1) is None


def test_parser_accepts_markdown_json_fence_only() -> None:
    parser = GameIntentCommandParser(frozenset({"shiritori"}))
    raw = (
        "```json\n"
        '{"intent":"normal_chat","game_type":null,"confidence":0.9,'
        '"game_move":null,"chat_text":"暑いね","control":null,'
        '"state_version":3,"requires_confirmation":false,"reason":"chat"}\n'
        "```"
    )

    command = parser.parse(raw, expected_state_version=3)

    assert command is not None
    assert command.intent == GameIntent.NORMAL_CHAT
