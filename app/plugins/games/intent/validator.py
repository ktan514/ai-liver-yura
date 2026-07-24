from __future__ import annotations

from dataclasses import dataclass

from app.plugins.games.game_engine import GameEngine
from app.plugins.games.intent.command import GameIntent, GameIntentCommand
from app.plugins.games.shiritori.state import ShiritoriPlayer, ShiritoriState
from app.shared.observability import PluginLogger


@dataclass(frozen=True, slots=True)
class GameCommandValidation:
    accepted: bool
    requires_confirmation: bool = False
    reason: str = ""


class GameCommandValidator:
    _allowed_controls = frozenset({"pause", "resume", "quit", "surrender"})

    def __init__(
        self, engine: GameEngine, *, confidence_threshold: float = 0.85
    ) -> None:
        self._engine = engine
        self._confidence_threshold = confidence_threshold
        self._trace_logger = PluginLogger(__name__)

    def validate(
        self,
        command: GameIntentCommand,
        *,
        current_state_version: int,
    ) -> GameCommandValidation:
        if command.state_version != current_state_version:
            return self._reject(
                command, "stale_state", "game_command_validator:stale_state"
            )
        if (
            command.requires_confirmation
            or command.confidence < self._confidence_threshold
        ):
            self._trace_logger.info(
                "game_command_validator:confirmation_required",
                intent=command.intent.value,
                confidence=command.confidence,
                state_version=command.state_version,
            )
            return GameCommandValidation(False, True, "confidence_or_confirmation")
        session = self._engine.get_active_session()
        if command.intent == GameIntent.START_GAME:
            if command.game_type is None or not self._engine.is_supported(
                command.game_type
            ):
                return self._reject(command, "unsupported_game")
            if session is not None:
                return self._reject(command, "active_session_exists")
        elif command.intent == GameIntent.PLAY_GAME_MOVE:
            if session is None or not command.game_move:
                return self._reject(command, "session_or_move_missing")
            state = session.metadata.get("shiritori_state")
            if (
                not isinstance(state, ShiritoriState)
                or state.current_turn != ShiritoriPlayer.USER
            ):
                return self._reject(command, "not_user_turn")
        elif command.intent == GameIntent.GAME_CONTROL:
            if session is None or command.control not in self._allowed_controls:
                return self._reject(command, "invalid_control")
        self._trace_logger.info(
            "game_command_validator:accepted",
            intent=command.intent.value,
            game_type=command.game_type,
            confidence=command.confidence,
            state_version=command.state_version,
        )
        return GameCommandValidation(True)

    def _reject(
        self,
        command: GameIntentCommand,
        reason: str,
        label: str = "game_command_validator:rejected",
    ) -> GameCommandValidation:
        self._trace_logger.warning(
            label,
            intent=command.intent.value,
            game_type=command.game_type,
            state_version=command.state_version,
            reason=reason,
        )
        return GameCommandValidation(False, False, reason)
