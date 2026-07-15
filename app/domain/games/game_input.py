from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GameInputClassification(str, Enum):
    GAME_START_REQUEST = "game_start_request"
    GAME_MOVE = "game_move"
    GAME_CONTROL = "game_control"
    GAME_CHAT = "game_chat"
    NORMAL_CHAT = "normal_chat"
    MIXED = "mixed"
    UNSUPPORTED_GAME_REQUEST = "unsupported_game_request"
    AMBIGUOUS = "ambiguous"


class GameControl(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    QUIT = "quit"
    SURRENDER = "surrender"
    RESTART = "restart"


@dataclass(frozen=True, slots=True)
class GameInputClassificationResult:
    classification: GameInputClassification
    confidence: float
    raw_text: str
    classifier_type: str
    game_type: str | None = None
    game_word: str | None = None
    game_control: GameControl | None = None
    chat_text: str | None = None
    requested_game: str | None = None
    reason: str = ""
    session_id: str | None = None
    session_status: str | None = None
