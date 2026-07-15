from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any


class ShiritoriPlayer(str, Enum):
    USER = "user"
    AI = "ai"


class ShiritoriValidation(str, Enum):
    VALID = "valid"
    INVALID_HEAD = "invalid_head"
    ALREADY_USED = "already_used"
    ENDS_WITH_N = "ends_with_n"
    NOT_USER_TURN = "not_user_turn"
    NOT_AI_TURN = "not_ai_turn"
    GAME_FINISHED = "game_finished"
    INVALID_WORD = "invalid_word"


@dataclass(frozen=True, slots=True)
class ShiritoriState:
    current_turn: ShiritoriPlayer
    last_word: str | None = None
    expected_head: str | None = None
    used_words: tuple[str, ...] = ()
    turn_count: int = 0
    winner: ShiritoriPlayer | None = None
    loser: ShiritoriPlayer | None = None
    end_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ShiritoriWordResult:
    validation: ShiritoriValidation
    word: str | None
    state: ShiritoriState


@dataclass(frozen=True, slots=True)
class ShiritoriAiOutput:
    game_action: str
    word: str
    utterance: str


class ShiritoriGameDefinition:
    game_type = "shiritori"
    display_name = "しりとり"
    description = "ユーザーと日本語の単語を交互につなぐゲーム"
    supported = True

    def create_initial_state(self) -> dict[str, Any]:
        return {
            "shiritori_state": ShiritoriState(current_turn=ShiritoriPlayer.AI),
        }


_REMOVE_CHARACTERS = "、。,.!！?？『』「」\"'（）()【】[]〈〉《》"
_SMALL_TO_LARGE = {
    "ゃ": "や",
    "ゅ": "ゆ",
    "ょ": "よ",
    "ぁ": "あ",
    "ぃ": "い",
    "ぅ": "う",
    "ぇ": "え",
    "ぉ": "お",
    "っ": "つ",
    "ゎ": "わ",
}


def normalize_shiritori_word(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"[\s\u3000]", "", normalized)
    normalized = normalized.translate(str.maketrans("", "", _REMOVE_CHARACTERS))
    return "".join(
        chr(ord(character) - 0x60) if "ァ" <= character <= "ヶ" else character
        for character in normalized
    )


def get_shiritori_head(word: str) -> str | None:
    normalized = normalize_shiritori_word(word)
    if not normalized:
        return None
    return _SMALL_TO_LARGE.get(normalized[0], normalized[0])


def get_shiritori_tail(word: str) -> str | None:
    normalized = normalize_shiritori_word(word)
    if not normalized:
        return None
    index = len(normalized) - 1
    while index >= 0 and normalized[index] == "ー":
        index -= 1
    if index < 0:
        return None
    return _SMALL_TO_LARGE.get(normalized[index], normalized[index])


def validate_shiritori_word(
    state: ShiritoriState,
    value: str,
    *,
    player: ShiritoriPlayer,
) -> ShiritoriWordResult:
    if state.winner is not None or state.end_reason is not None:
        return ShiritoriWordResult(ShiritoriValidation.GAME_FINISHED, None, state)
    if state.current_turn != player:
        validation = (
            ShiritoriValidation.NOT_USER_TURN
            if player == ShiritoriPlayer.USER
            else ShiritoriValidation.NOT_AI_TURN
        )
        return ShiritoriWordResult(validation, None, state)
    word = normalize_shiritori_word(value)
    if not word or not re.fullmatch(r"[ぁ-ゖー]+", word):
        return ShiritoriWordResult(ShiritoriValidation.INVALID_WORD, None, state)
    if state.expected_head is not None and get_shiritori_head(word) != state.expected_head:
        return ShiritoriWordResult(ShiritoriValidation.INVALID_HEAD, word, state)
    if word in state.used_words:
        return ShiritoriWordResult(ShiritoriValidation.ALREADY_USED, word, state)
    if get_shiritori_tail(word) == "ん":
        winner = ShiritoriPlayer.AI if player == ShiritoriPlayer.USER else ShiritoriPlayer.USER
        ended = replace(
            state,
            last_word=word,
            used_words=(*state.used_words, word),
            turn_count=state.turn_count + 1,
            winner=winner,
            loser=player,
            end_reason=f"{player.value}_word_ends_with_n",
        )
        return ShiritoriWordResult(ShiritoriValidation.ENDS_WITH_N, word, ended)
    next_player = ShiritoriPlayer.AI if player == ShiritoriPlayer.USER else ShiritoriPlayer.USER
    advanced = replace(
        state,
        current_turn=next_player,
        last_word=word,
        expected_head=get_shiritori_tail(word),
        used_words=(*state.used_words, word),
        turn_count=state.turn_count + 1,
    )
    return ShiritoriWordResult(ShiritoriValidation.VALID, word, advanced)
