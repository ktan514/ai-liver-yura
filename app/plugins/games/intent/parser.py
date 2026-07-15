from __future__ import annotations

import json

from app.plugins.games.intent.command import GameIntent, GameIntentCommand


class GameIntentCommandParser:
    def __init__(self, supported_games: frozenset[str]) -> None:
        self._supported_games = supported_games

    def parse(self, raw_output: str, *, expected_state_version: int) -> GameIntentCommand | None:
        text = raw_output.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or lines[-1].strip() != "```":
                return None
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(value, dict):
            return None
        required = {"intent", "confidence", "state_version", "requires_confirmation", "reason"}
        if not required.issubset(value):
            return None
        try:
            intent = GameIntent(value["intent"])
        except (TypeError, ValueError):
            return None
        confidence = value["confidence"]
        state_version = value["state_version"]
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0.0 <= float(confidence) <= 1.0
            or not isinstance(state_version, int)
            or isinstance(state_version, bool)
            or state_version != expected_state_version
            or not isinstance(value["requires_confirmation"], bool)
            or not isinstance(value["reason"], str)
        ):
            return None
        game_type = value.get("game_type")
        if game_type is not None and (
            not isinstance(game_type, str) or game_type not in self._supported_games
        ):
            return None
        game_move = value.get("game_move")
        chat_text = value.get("chat_text")
        control = value.get("control")
        constraints = value.get("constraints", {})
        if not isinstance(constraints, dict) or not all(
            isinstance(key, str) for key in constraints
        ):
            return None
        if intent == GameIntent.PLAY_GAME_MOVE and not isinstance(game_move, str):
            return None
        if intent == GameIntent.GAME_CONTROL and not isinstance(control, str):
            return None
        if intent == GameIntent.MIXED and (
            not isinstance(game_move, str) or not isinstance(chat_text, str)
        ):
            return None
        return GameIntentCommand(
            intent=intent,
            game_type=game_type,
            confidence=float(confidence),
            state_version=state_version,
            game_move=game_move if isinstance(game_move, str) else None,
            chat_text=chat_text if isinstance(chat_text, str) else None,
            control=control if isinstance(control, str) else None,
            constraints=constraints,
            requires_confirmation=value["requires_confirmation"],
            reason=value["reason"],
            classifier_type="llm",
        )
