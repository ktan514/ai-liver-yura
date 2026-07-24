from __future__ import annotations

import pytest

from app.plugins.games.activity_factory import TransientGameActivityFactory
from app.plugins.games.engine import GameEngine
from app.plugins.games.shiritori.domain import (
    ShiritoriGameDefinition,
    ShiritoriPlayer,
    ShiritoriState,
    ShiritoriValidation,
    get_shiritori_head,
    get_shiritori_tail,
    normalize_shiritori_word,
    validate_shiritori_word,
)
from app.plugins.games.shiritori.service import ShiritoriGameService


class SequenceResponseGenerator:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.call_count = 0

    async def generate_response(self, activity: object) -> str:
        self.call_count += 1
        return self._responses.pop(0)


def _create_service() -> (
    tuple[GameEngine, TransientGameActivityFactory, ShiritoriGameService]
):
    engine = GameEngine((ShiritoriGameDefinition(),))
    manager = TransientGameActivityFactory()
    return engine, manager, ShiritoriGameService(engine)


def test_shiritori_definition_and_initial_turns() -> None:
    engine, manager, service = _create_service()

    ai_session, _ = service.start_game(manager)
    assert engine.is_supported("shiritori") is True
    assert ai_session.metadata["shiritori_state"] == ShiritoriState(
        current_turn=ShiritoriPlayer.AI
    )

    engine.cancel_game("test_reset")
    user_session, _ = service.start_game(manager, started_by=ShiritoriPlayer.USER)
    user_state = user_session.metadata["shiritori_state"]
    assert user_state.current_turn == ShiritoriPlayer.USER
    assert user_state.used_words == ()


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        ("  ウミ　", "うみ"),
        ("『たこ』", "たこ"),
        ('"キャベツ"', "きゃべつ"),
    ],
)
def test_normalize_shiritori_word(value: str, normalized: str) -> None:
    assert normalize_shiritori_word(value) == normalized


def test_head_tail_long_vowel_and_small_character_rules() -> None:
    assert get_shiritori_head("キャベツ") == "き"
    assert get_shiritori_tail("キャベツ") == "つ"
    assert get_shiritori_tail("ミネラルウォーター") == "た"
    assert get_shiritori_tail("どきゅ") == "ゆ"


def test_user_word_validation_rules() -> None:
    state = ShiritoriState(
        current_turn=ShiritoriPlayer.USER,
        expected_head="う",
        used_words=("うさぎ",),
    )

    assert (
        validate_shiritori_word(state, "うみ", player=ShiritoriPlayer.USER).validation
        == ShiritoriValidation.VALID
    )
    assert (
        validate_shiritori_word(state, "たこ", player=ShiritoriPlayer.USER).validation
        == ShiritoriValidation.INVALID_HEAD
    )
    assert (
        validate_shiritori_word(state, "うさぎ", player=ShiritoriPlayer.USER).validation
        == ShiritoriValidation.ALREADY_USED
    )
    assert (
        validate_shiritori_word(state, "", player=ShiritoriPlayer.USER).validation
        == ShiritoriValidation.INVALID_WORD
    )
    assert (
        validate_shiritori_word(state, "うどん", player=ShiritoriPlayer.USER).validation
        == ShiritoriValidation.ENDS_WITH_N
    )
    assert (
        validate_shiritori_word(
            replace_turn(state, ShiritoriPlayer.AI), "うみ", player=ShiritoriPlayer.USER
        ).validation
        == ShiritoriValidation.NOT_USER_TURN
    )


def replace_turn(state: ShiritoriState, turn: ShiritoriPlayer) -> ShiritoriState:
    return ShiritoriState(
        current_turn=turn,
        last_word=state.last_word,
        expected_head=state.expected_head,
        used_words=state.used_words,
        turn_count=state.turn_count,
    )


def test_ai_word_uses_same_validation_rules() -> None:
    state = ShiritoriState(
        current_turn=ShiritoriPlayer.AI,
        expected_head="た",
        used_words=("たぬき",),
    )

    assert (
        validate_shiritori_word(state, "たこ", player=ShiritoriPlayer.AI).validation
        == ShiritoriValidation.VALID
    )
    assert (
        validate_shiritori_word(state, "こあら", player=ShiritoriPlayer.AI).validation
        == ShiritoriValidation.INVALID_HEAD
    )
    assert (
        validate_shiritori_word(state, "たぬき", player=ShiritoriPlayer.AI).validation
        == ShiritoriValidation.ALREADY_USED
    )
    assert (
        validate_shiritori_word(state, "たん", player=ShiritoriPlayer.AI).validation
        == ShiritoriValidation.ENDS_WITH_N
    )


@pytest.mark.asyncio
async def test_ai_structured_output_updates_state_and_uses_utterance() -> None:
    engine, manager, service = _create_service()
    _, activity = service.start_game(manager)
    generator = SequenceResponseGenerator(
        [
            '{"game_action":"play_word","word":"うみ","utterance":"「うみ」！ 次は「み」だよ。"}'
        ]
    )
    utterance = await service.generate_ai_turn(activity, generator)

    state = engine.get_active_session().metadata["shiritori_state"]  # type: ignore[union-attr]
    assert state.last_word == "うみ"
    assert state.expected_head == "み"
    assert state.current_turn == ShiritoriPlayer.USER
    assert state.used_words == ("うみ",)
    assert state.turn_count == 1
    assert utterance == "「うみ」！ 次は「み」だよ。"


@pytest.mark.asyncio
async def test_game_progression_water_requires_ta_for_next_ai_word() -> None:
    engine, manager, service = _create_service()
    _, first_activity = service.start_game(manager)
    first_generator = SequenceResponseGenerator(
        ['{"game_action":"play_word","word":"うみ","utterance":"うみ！"}']
    )
    await service.generate_ai_turn(first_activity, first_generator)

    user_result, ai_activity = service.submit_user_word(manager, "ミネラルウォーター")

    assert user_result.validation == ShiritoriValidation.VALID
    assert user_result.state.expected_head == "た"
    second_generator = SequenceResponseGenerator(
        ['{"game_action":"play_word","word":"たこ","utterance":"じゃあ「たこ」！"}']
    )
    await service.generate_ai_turn(ai_activity, second_generator)
    state = engine.get_active_session().metadata["shiritori_state"]  # type: ignore[union-attr]
    assert state.last_word == "たこ"
    assert state.expected_head == "こ"
    assert state.used_words == ("うみ", "みねらるうぉーたー", "たこ")


@pytest.mark.asyncio
async def test_invalid_ai_output_retries_finitely_then_accepts_valid_word() -> None:
    _, manager, service = _create_service()
    _, activity = service.start_game(manager)
    generator = SequenceResponseGenerator(
        [
            "not-json",
            '{"game_action":"play_word","word":"うどん","utterance":"うどん"}',
            '{"game_action":"play_word","word":"うみ","utterance":"うみ！"}',
        ]
    )

    utterance = await service.generate_ai_turn(activity, generator)

    assert utterance == "うみ！"
    assert generator.call_count == 3


@pytest.mark.asyncio
async def test_ai_generation_limit_without_fallback_completes_as_surrender() -> None:
    engine, manager, service = _create_service()
    session, _ = service.start_game(manager, started_by=ShiritoriPlayer.USER)
    state = ShiritoriState(
        current_turn=ShiritoriPlayer.AI,
        expected_head="そ",
        used_words=("うそ",),
        turn_count=1,
    )
    engine.update_active_session(
        metadata={**session.metadata, "shiritori_state": state},
        current_turn=1,
    )
    active = engine.get_active_session()
    assert active is not None
    activity = manager.create_game_activity(
        active,
        goal="AI単語を生成する",
        context_updates={"shiritori_action": "generate_ai_word"},
    )
    generator = SequenceResponseGenerator(["invalid", "invalid", "invalid"])

    utterance = await service.generate_ai_turn(activity, generator)

    assert "私の負け" in utterance
    assert generator.call_count == 3
    assert engine.get_active_session() is None
    completed = engine.get_current_session()
    assert completed is not None
    assert completed.end_reason == "ai_surrendered"


def test_parse_ai_output_separates_word_and_utterance() -> None:
    parsed = ShiritoriGameService.parse_ai_output(
        '```json\n{"game_action":"play_word","word":"たこ","utterance":"たこ！"}\n```'
    )

    assert parsed is not None
    assert parsed.word == "たこ"
    assert parsed.utterance == "たこ！"


def test_user_word_ending_with_n_completes_session_with_ai_winner() -> None:
    engine, manager, service = _create_service()
    service.start_game(manager, started_by=ShiritoriPlayer.USER)

    result, _ = service.submit_user_word(manager, "みかん")

    assert result.validation == ShiritoriValidation.ENDS_WITH_N
    assert result.state.winner == ShiritoriPlayer.AI
    assert result.state.loser == ShiritoriPlayer.USER
    assert result.state.end_reason == "user_word_ends_with_n"
    assert engine.get_active_session() is None

    finished_result, _ = service.submit_user_word(manager, "うみ")
    assert finished_result.validation == ShiritoriValidation.GAME_FINISHED
