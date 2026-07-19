from __future__ import annotations

import logging
import re

from app.plugins.games.game_engine import GameEngine
from app.plugins.games.game_session import GameSession
from app.plugins.games.intent.command import GameIntent, GameIntentCommand
from app.plugins.games.intent.parser import GameIntentCommandParser
from app.plugins.games.intent.prompt import build_game_intent_prompt
from app.plugins.games.shiritori.rules import (
    get_shiritori_head,
    normalize_shiritori_word,
)
from app.plugins.games.shiritori.state import ShiritoriPlayer, ShiritoriState
from app.shared.contracts.plugins.runtime import (
    PluginLlmRequest,
    ResponseGenerationGateway,
)


class GameIntentInterpreter:
    _controls = {
        "pause": ("ちょっと待って", "一時停止"),
        "resume": ("再開", "続けよう"),
        "quit": ("やめよう", "終了", "終わろう"),
        "surrender": ("降参", "負けた"),
    }
    _safe_start_markers = (
        "しりとりしよう",
        "しりとりしよ",
        "しりとりしたい",
        "しりとりやろう",
    )
    _never_start_markers = (
        "知ってる",
        "得意",
        "ルール",
        "るーる",
        "昨日",
        "やりたくない",
        "負けたこと",
        "負けた",
    )

    def __init__(
        self,
        engine: GameEngine,
        response_generator: ResponseGenerationGateway,
        *,
        max_attempts: int = 2,
    ) -> None:
        self._engine = engine
        self._response_generator = response_generator
        self._max_attempts = max_attempts
        self._parser = GameIntentCommandParser(
            frozenset(game.game_type for game in engine.list_supported_games())
        )
        self._logger = logging.getLogger(__name__)

    async def interpret(self, text: str, *, state_version: int) -> GameIntentCommand:
        session = self._engine.get_active_session()
        deterministic = self._deterministic(text, session, state_version)
        if deterministic is not None:
            self._write("game_intent_interpreter:deterministic_match", deterministic)
            return deterministic
        if not self._game_related_candidate(text, session):
            return self._command(
                GameIntent.NOT_HANDLED,
                state_version,
                confidence=1.0,
                chat_text=text,
                reason="no_game_related_signal",
            )
        prompt = build_game_intent_prompt(
            user_text=text,
            session=session,
            state_version=state_version,
            supported_games=tuple(
                (game.game_type, game.display_name, (game.display_name,))
                for game in self._engine.list_supported_games()
            ),
        )
        self._logger.debug(
            "game intent LLM requested: state_version=%s game_type=%s",
            state_version,
            session.game_type if session else None,
        )
        for attempt in range(self._max_attempts):
            request = PluginLlmRequest(
                purpose="game_intent_classification",
                prompt=prompt,
                context={
                    "retry_count": attempt,
                    "user_input": text,
                    "plugin_session_id": session.session_id if session else None,
                    "planner_state": {
                        "state_version": state_version,
                        "game_type": session.game_type if session else None,
                    },
                    "constraints": ["JSONだけを返す", "ゲーム状態を更新しない"],
                },
            )
            try:
                raw = await self._response_generator.generate_response(request)
            except Exception as error:
                self._logger.warning(
                    "game intent LLM failed: error=%s attempt=%s",
                    type(error).__name__,
                    attempt,
                )
                continue
            command = self._parser.parse(raw, expected_state_version=state_version)
            self._logger.debug(
                "game intent LLM response: request_id=%s parsed=%s",
                request.request_id,
                command is not None,
            )
            if command is not None:
                self._write("game_intent_interpreter:command_parsed", command)
                self._write("game_intent_interpreter:llm_succeeded", command)
                return command
            self._logger.warning(
                "game intent command rejected: state_version=%s attempt=%s",
                state_version,
                attempt,
            )
            self._logger.debug(
                "game intent retry scheduled: attempt=%s next=%s",
                attempt,
                attempt + 1 if attempt + 1 < self._max_attempts else None,
            )
        fallback = self._command(
            GameIntent.AMBIGUOUS,
            state_version,
            confidence=0.0,
            chat_text=text,
            requires_confirmation=True,
            reason="intent_interpreter_unavailable",
            classifier_type="fallback",
        )
        self._write("game_intent_interpreter:fallback", fallback)
        return fallback

    def _deterministic(
        self,
        text: str,
        session: GameSession | None,
        state_version: int,
    ) -> GameIntentCommand | None:
        stripped = text.strip()
        normalized = normalize_shiritori_word(stripped.replace("しり取り", "しりとり"))
        if session is None:
            if "しりとり" in normalized and any(
                marker in normalized for marker in self._never_start_markers
            ):
                return self._command(
                    GameIntent.NORMAL_CHAT,
                    state_version,
                    confidence=0.99,
                    chat_text=stripped,
                    reason="question_negative_or_past_reference",
                )
            if any(marker in normalized for marker in self._safe_start_markers):
                return self._command(
                    GameIntent.START_GAME,
                    state_version,
                    game_type="shiritori",
                    confidence=0.99,
                    reason="explicit_safe_start_request",
                )
            return None
        for control, markers in self._controls.items():
            if any(marker in stripped for marker in markers):
                return self._command(
                    GameIntent.GAME_CONTROL,
                    state_version,
                    game_type=session.game_type,
                    confidence=0.98,
                    control=control,
                    reason="explicit_game_control",
                )
        state = session.metadata.get("shiritori_state")
        word = normalize_shiritori_word(stripped)
        if (
            isinstance(state, ShiritoriState)
            and state.current_turn == ShiritoriPlayer.USER
            and re.fullmatch(r"[ぁ-ゖー]+", word)
            and (
                state.expected_head is None
                or get_shiritori_head(word) == state.expected_head
            )
        ):
            return self._command(
                GameIntent.PLAY_GAME_MOVE,
                state_version,
                game_type=session.game_type,
                confidence=0.99,
                game_move=word,
                reason="single_word_matches_expected_input",
            )
        return None

    def _game_related_candidate(self, text: str, session: GameSession | None) -> bool:
        if session is not None:
            return True
        return any(
            marker in text
            for marker in ("しりとり", "しり取り", "シリトリ", "言葉遊び", "遊ぼ")
        )

    @staticmethod
    def _command(
        intent: GameIntent,
        state_version: int,
        *,
        confidence: float,
        game_type: str | None = None,
        game_move: str | None = None,
        chat_text: str | None = None,
        control: str | None = None,
        requires_confirmation: bool = False,
        reason: str,
        classifier_type: str = "deterministic",
    ) -> GameIntentCommand:
        return GameIntentCommand(
            intent=intent,
            game_type=game_type,
            confidence=confidence,
            state_version=state_version,
            game_move=game_move,
            chat_text=chat_text,
            control=control,
            requires_confirmation=requires_confirmation,
            reason=reason,
            classifier_type=classifier_type,
        )

    def _write(self, label: str, command: GameIntentCommand) -> None:
        self._logger.debug(
            "%s: intent=%s game_type=%s confidence=%s classifier=%s state_version=%s reason=%s",
            label,
            command.intent.value,
            command.game_type,
            command.confidence,
            command.classifier_type,
            command.state_version,
            command.reason,
        )
