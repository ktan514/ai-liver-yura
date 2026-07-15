from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType


def _empty_constraints() -> Mapping[str, object]:
    return MappingProxyType({})


class GameIntent(str, Enum):
    START_GAME = "start_game"
    PLAY_GAME_MOVE = "play_game_move"
    GAME_CONTROL = "game_control"
    GAME_CHAT = "game_chat"
    NORMAL_CHAT = "normal_chat"
    MIXED = "mixed"
    UNSUPPORTED_GAME_REQUEST = "unsupported_game_request"
    AMBIGUOUS = "ambiguous"
    NOT_HANDLED = "not_handled"


@dataclass(frozen=True, slots=True)
class GameIntentCommand:
    intent: GameIntent
    game_type: str | None
    confidence: float
    state_version: int
    game_move: str | None = None
    chat_text: str | None = None
    control: str | None = None
    constraints: Mapping[str, object] = field(default_factory=_empty_constraints)
    requires_confirmation: bool = False
    reason: str = ""
    classifier_type: str = "deterministic"
