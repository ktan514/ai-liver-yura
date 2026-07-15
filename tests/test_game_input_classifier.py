from __future__ import annotations

import pytest

from app.domain.activities import Activity
from app.domain.games import (
    GameControl,
    GameInputClassification,
    ShiritoriGameDefinition,
    ShiritoriPlayer,
    ShiritoriState,
)
from app.runtime.game_engine import GameEngine
from app.runtime.game_input_classifier import GameInputClassifier


class StubResponseGenerator:
    def __init__(self, response: str) -> None:
        self.response = response
        self.activities: list[Activity] = []

    async def generate_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return self.response


def _engine(*, expected_head: str = "み") -> GameEngine:
    engine = GameEngine([ShiritoriGameDefinition()])
    engine.start_game(
        "shiritori",
        metadata={
            "shiritori_state": ShiritoriState(
                current_turn=ShiritoriPlayer.USER,
                last_word="はさみ",
                expected_head=expected_head,
                used_words=("はさみ",),
                turn_count=1,
            )
        },
    )
    return engine


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "classification", "detail"),
    [
        ("ミネラルウォーター", GameInputClassification.GAME_MOVE, "みねらるうぉーたー"),
        ("今の単語ずるくない？", GameInputClassification.GAME_CHAT, None),
        ("今日は暑いね", GameInputClassification.NORMAL_CHAT, None),
        ("みかん。そういえば果物は好き？", GameInputClassification.MIXED, "みかん"),
        ("ちょっと待って", GameInputClassification.GAME_CONTROL, GameControl.PAUSE),
        ("再開しよう", GameInputClassification.GAME_CONTROL, GameControl.RESUME),
        ("しりとりをやめる", GameInputClassification.GAME_CONTROL, GameControl.QUIT),
        ("降参する", GameInputClassification.GAME_CONTROL, GameControl.SURRENDER),
        ("最初からやり直そう", GameInputClassification.GAME_CONTROL, GameControl.RESTART),
        ("チェスをしよう", GameInputClassification.UNSUPPORTED_GAME_REQUEST, "チェス"),
        ("それでいいよ", GameInputClassification.AMBIGUOUS, None),
    ],
)
async def test_deterministic_classification_does_not_change_session(
    text: str,
    classification: GameInputClassification,
    detail: str | GameControl | None,
) -> None:
    engine = _engine()
    before = engine.get_current_session()

    result = await GameInputClassifier(engine).classify(text)

    assert result.classification == classification
    if classification in {GameInputClassification.GAME_MOVE, GameInputClassification.MIXED}:
        assert result.game_word == detail
    elif classification == GameInputClassification.GAME_CONTROL:
        assert result.game_control == detail
    elif classification == GameInputClassification.UNSUPPORTED_GAME_REQUEST:
        assert result.requested_game == detail
    assert engine.get_current_session() == before


@pytest.mark.asyncio
async def test_no_active_game_is_normal_chat_without_llm() -> None:
    generator = StubResponseGenerator("should not be used")

    result = await GameInputClassifier(GameEngine(), generator).classify("りんご")

    assert result.classification == GameInputClassification.NORMAL_CHAT
    assert generator.activities == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "しりとりしよう",
        "しりとりしましょ",
        "しりとりしませんか",
        "シリトリやろう",
        "ゲームしない？しりとりしようよ",
        "一緒にしり取りやろ",
    ],
)
async def test_explicit_shiritori_start_request_is_deterministic(text: str) -> None:
    generator = StubResponseGenerator("should not be used")
    engine = GameEngine([ShiritoriGameDefinition()])

    result = await GameInputClassifier(engine, generator).classify(text)

    assert result.classification == GameInputClassification.GAME_START_REQUEST
    assert result.requested_game == "shiritori"
    assert result.classifier_type == "deterministic"
    assert engine.get_current_session() is None
    assert generator.activities == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    ["しりとりって知ってる？", "しりとりは難しい？", "ゲームは好き？"],
)
async def test_game_question_does_not_start_game(text: str) -> None:
    engine = GameEngine([ShiritoriGameDefinition()])

    result = await GameInputClassifier(engine).classify(text)

    assert result.classification == GameInputClassification.NORMAL_CHAT
    assert engine.get_current_session() is None


@pytest.mark.asyncio
async def test_vague_game_proposal_can_be_classified_by_llm() -> None:
    generator = StubResponseGenerator(
        '{"classification":"ambiguous","confidence":0.6,'
        '"game_word":null,"game_control":null,"chat_text":"何かゲームでもやる？",'
        '"requested_game":null,"reason":"game_not_identified"}'
    )
    engine = GameEngine([ShiritoriGameDefinition()])

    result = await GameInputClassifier(engine, generator).classify("何かゲームでもやる？")

    assert result.classification == GameInputClassification.AMBIGUOUS
    assert result.classifier_type == "llm"
    assert len(generator.activities) == 1


@pytest.mark.asyncio
async def test_vague_supported_game_request_can_be_resolved_by_llm() -> None:
    generator = StubResponseGenerator(
        '{"classification":"game_start_request","confidence":0.87,'
        '"game_word":null,"game_control":null,"chat_text":null,'
        '"requested_game":"shiritori","reason":"word_chain_game_requested"}'
    )
    engine = GameEngine([ShiritoriGameDefinition()])

    result = await GameInputClassifier(engine, generator).classify("言葉をつなぐやつやりたい")

    assert result.classification == GameInputClassification.GAME_START_REQUEST
    assert result.requested_game == "shiritori"
    assert result.classifier_type == "llm"


@pytest.mark.asyncio
async def test_start_request_during_active_game_does_not_restart() -> None:
    engine = _engine()
    session = engine.get_current_session()

    result = await GameInputClassifier(engine).classify("しりとりしよう")

    assert result.classification == GameInputClassification.AMBIGUOUS
    assert result.reason == "supported_game_already_active"
    assert engine.get_current_session() == session


@pytest.mark.asyncio
async def test_undecidable_input_uses_llm_structured_result() -> None:
    generator = StubResponseGenerator(
        '{"classification":"game_chat","confidence":0.82,'
        '"game_word":null,"game_control":null,"chat_text":"どうかな",'
        '"requested_game":null,"reason":"game_context_question"}'
    )
    classifier = GameInputClassifier(_engine(), generator)

    result = await classifier.classify("どうかな")

    assert result.classification == GameInputClassification.GAME_CHAT
    assert result.classifier_type == "llm"
    assert generator.activities[0].context["expected_head"] == "み"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{"classification":"unknown","confidence":1}',
        '{"classification":"game_move","confidence":1,"game_word":null}',
        '{"classification":"mixed","confidence":1,"game_word":"みかん"}',
    ],
)
async def test_invalid_llm_output_falls_back_to_ambiguous(response: str) -> None:
    result = await GameInputClassifier(_engine(), StubResponseGenerator(response)).classify(
        "どうかな"
    )

    assert result.classification == GameInputClassification.AMBIGUOUS
    assert result.classifier_type == "fallback"
    assert result.confidence == 0.0
