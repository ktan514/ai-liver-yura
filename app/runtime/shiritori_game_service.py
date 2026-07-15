from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace

from app.domain.activities import Activity
from app.domain.emotions import EmotionState
from app.domain.games import (
    GameSession,
    ShiritoriAiOutput,
    ShiritoriPlayer,
    ShiritoriState,
    ShiritoriValidation,
    ShiritoriWordResult,
    validate_shiritori_word,
)
from app.ports.response_generator import ResponseGenerator
from app.runtime.activity_manager import ActivityManager
from app.runtime.game_engine import GameEngine
from app.utils.trace import TraceLogger


class ShiritoriGameService:
    """しりとりルールと既存Activity/ResponseGenerator経路を接続する。"""

    def __init__(
        self,
        game_engine: GameEngine,
        *,
        emotion_provider: Callable[[], EmotionState] | None = None,
        max_generation_attempts: int = 3,
    ) -> None:
        self._game_engine = game_engine
        self._emotion_provider = emotion_provider
        self._max_generation_attempts = max_generation_attempts
        self._trace_logger = TraceLogger()

    def start_game(
        self,
        activity_manager: ActivityManager,
        *,
        started_by: ShiritoriPlayer = ShiritoriPlayer.AI,
        constraints: dict[str, object] | None = None,
    ) -> tuple[GameSession, Activity]:
        state = ShiritoriState(current_turn=started_by)
        session = self._game_engine.start_game(
            "shiritori",
            metadata={
                "shiritori_state": state,
                "activity_constraints": dict(constraints or {}),
            },
        )
        self._trace_logger.info(
            "shiritori:session_initialized",
            session_id=session.session_id,
            current_turn=state.current_turn.value,
            turn_count=state.turn_count,
        )
        try:
            activity = self._create_activity(
                activity_manager,
                session,
                action="generate_ai_word"
                if started_by == ShiritoriPlayer.AI
                else "await_user_word",
                validation=None,
            )
        except Exception:
            current = self._game_engine.get_active_session()
            if current is not None and current.session_id == session.session_id:
                self._game_engine.cancel_game("shiritori_activity_creation_failed")
            raise
        return session, activity

    def submit_user_word(
        self,
        activity_manager: ActivityManager,
        value: str,
    ) -> tuple[ShiritoriWordResult, Activity]:
        current = self._game_engine.get_current_session()
        if current is not None and current.game_type == "shiritori":
            current_state = current.metadata.get("shiritori_state")
            if isinstance(current_state, ShiritoriState) and current_state.end_reason is not None:
                result = ShiritoriWordResult(
                    ShiritoriValidation.GAME_FINISHED,
                    None,
                    current_state,
                )
                return result, self._create_activity(
                    activity_manager,
                    current,
                    action="express_invalid_word",
                    validation=result.validation,
                )
        session, state = self._active_state()
        self._trace_logger.info(
            "shiritori:user_word_received",
            session_id=session.session_id,
            turn_count=state.turn_count,
            current_turn=state.current_turn.value,
            expected_head=state.expected_head,
        )
        result = validate_shiritori_word(state, value, player=ShiritoriPlayer.USER)
        label = (
            "shiritori:user_word_validated"
            if result.validation in {ShiritoriValidation.VALID, ShiritoriValidation.ENDS_WITH_N}
            else "shiritori:user_word_rejected"
        )
        self._trace_logger.info(
            label,
            session_id=session.session_id,
            word=result.word,
            validation_result=result.validation.value,
            expected_head=state.expected_head,
            turn_count=result.state.turn_count,
        )
        if result.validation == ShiritoriValidation.ENDS_WITH_N:
            completed = self._complete_from_state(result.state)
            return result, self._create_activity(
                activity_manager,
                completed,
                action="express_game_result",
                validation=result.validation,
            )
        if result.validation == ShiritoriValidation.VALID:
            session = self._store_state(result.state)
            self._write_turn_advanced(session, result.state, result.word)
            return result, self._create_activity(
                activity_manager,
                session,
                action="generate_ai_word",
                validation=result.validation,
            )
        return result, self._create_activity(
            activity_manager,
            session,
            action="express_invalid_word",
            validation=result.validation,
        )

    async def generate_ai_turn(
        self,
        activity: Activity,
        response_generator: ResponseGenerator,
    ) -> str:
        session, state = self._active_state()
        for retry_count in range(self._max_generation_attempts):
            self._trace_logger.debug(
                "shiritori:ai_generation_requested",
                session_id=session.session_id,
                retry_count=retry_count,
                expected_head=state.expected_head,
                turn_count=state.turn_count,
            )
            attempt_activity = replace(
                activity,
                context={**activity.context, "shiritori_retry_count": retry_count},
            )
            raw_output = await response_generator.generate_response(attempt_activity)
            parsed = self.parse_ai_output(raw_output)
            if parsed is None:
                self._write_ai_rejected(session, retry_count, "invalid_structured_output")
                continue
            result = validate_shiritori_word(
                state,
                parsed.word,
                player=ShiritoriPlayer.AI,
            )
            if result.validation != ShiritoriValidation.VALID:
                self._write_ai_rejected(session, retry_count, result.validation.value)
                continue
            stored = self._store_state(result.state)
            is_initial_word = state.turn_count == 0
            self._trace_logger.info(
                "shiritori:initial_word_generated"
                if is_initial_word
                else "shiritori:ai_word_generated",
                session_id=stored.session_id,
                word=result.word,
                retry_count=retry_count,
                turn_count=result.state.turn_count,
            )
            self._write_turn_advanced(stored, result.state, result.word)
            if is_initial_word:
                self._trace_logger.info(
                    "shiritori:initial_turn_advanced",
                    session_id=stored.session_id,
                    initial_word=result.word,
                    current_turn=result.state.current_turn.value,
                    expected_head=result.state.expected_head,
                    turn_count=result.state.turn_count,
                )
            return parsed.utterance.strip() or str(result.word)

        fallback = self._fallback_word(state)
        if fallback is not None:
            result = validate_shiritori_word(state, fallback, player=ShiritoriPlayer.AI)
            if result.validation == ShiritoriValidation.VALID:
                stored = self._store_state(result.state)
                self._trace_logger.warning(
                    "shiritori:generation_fallback",
                    session_id=stored.session_id,
                    word=fallback,
                    retry_count=self._max_generation_attempts,
                )
                if state.turn_count == 0:
                    self._trace_logger.info(
                        "shiritori:initial_word_generated",
                        session_id=stored.session_id,
                        word=fallback,
                        retry_count=self._max_generation_attempts,
                        turn_count=result.state.turn_count,
                    )
                    self._trace_logger.info(
                        "shiritori:initial_turn_advanced",
                        session_id=stored.session_id,
                        initial_word=fallback,
                        current_turn=result.state.current_turn.value,
                        expected_head=result.state.expected_head,
                        turn_count=result.state.turn_count,
                    )
                return f"『{fallback}』！ 次は『{result.state.expected_head}』だよ。"
        surrendered = replace(
            state,
            winner=ShiritoriPlayer.USER,
            loser=ShiritoriPlayer.AI,
            end_reason="ai_surrendered",
        )
        self._complete_from_state(surrendered)
        return "うーん、言葉が思いつかなかったよ。今回は私の負け！"

    def surrender(
        self,
        activity_manager: ActivityManager,
        *,
        player: ShiritoriPlayer,
    ) -> Activity:
        session, state = self._active_state()
        winner = ShiritoriPlayer.AI if player == ShiritoriPlayer.USER else ShiritoriPlayer.USER
        ended = replace(
            state,
            winner=winner,
            loser=player,
            end_reason=f"{player.value}_surrendered",
        )
        completed = self._complete_from_state(ended)
        return self._create_activity(
            activity_manager,
            completed,
            action="express_game_result",
            validation=None,
        )

    @staticmethod
    def parse_ai_output(raw_output: str) -> ShiritoriAiOutput | None:
        text = raw_output.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(value, dict):
            return None
        game_action = value.get("game_action")
        word = value.get("word")
        utterance = value.get("utterance")
        if (
            not isinstance(game_action, str)
            or not isinstance(word, str)
            or not isinstance(utterance, str)
        ):
            return None
        if game_action != "play_word":
            return None
        return ShiritoriAiOutput(game_action=game_action, word=word, utterance=utterance)

    def _active_state(self) -> tuple[GameSession, ShiritoriState]:
        session = self._game_engine.get_active_session()
        if session is None or session.game_type != "shiritori":
            raise RuntimeError("activeなしりとりSessionがありません。")
        state = session.metadata.get("shiritori_state")
        if not isinstance(state, ShiritoriState):
            raise RuntimeError("GameSessionのShiritoriStateが不正です。")
        return session, state

    def _store_state(self, state: ShiritoriState) -> GameSession:
        session, _ = self._active_state()
        return self._game_engine.update_active_session(
            metadata={**session.metadata, "shiritori_state": state},
            current_turn=state.turn_count,
        )

    def _complete_from_state(self, state: ShiritoriState) -> GameSession:
        session, _ = self._active_state()
        self._game_engine.update_active_session(
            metadata={**session.metadata, "shiritori_state": state},
            current_turn=state.turn_count,
        )
        completed = self._game_engine.complete_game(
            {
                "winner": state.winner.value if state.winner else None,
                "loser": state.loser.value if state.loser else None,
            },
            reason=state.end_reason or "shiritori_completed",
        )
        self._trace_logger.info(
            "shiritori:game_completed",
            session_id=completed.session_id,
            winner=state.winner.value if state.winner else None,
            loser=state.loser.value if state.loser else None,
            end_reason=state.end_reason,
            turn_count=state.turn_count,
        )
        return completed

    def _create_activity(
        self,
        activity_manager: ActivityManager,
        session: GameSession,
        *,
        action: str,
        validation: ShiritoriValidation | None,
    ) -> Activity:
        state = session.metadata.get("shiritori_state")
        if not isinstance(state, ShiritoriState):
            raise RuntimeError("GameSessionのShiritoriStateが不正です。")
        context: dict[str, object] = {
            "shiritori_action": action,
            "current_turn": state.current_turn.value,
            "last_word": state.last_word,
            "expected_head": state.expected_head,
            "used_words": list(state.used_words),
            "turn_count": state.turn_count,
            "validation_result": validation.value if validation else None,
            "winner": state.winner.value if state.winner else None,
            "loser": state.loser.value if state.loser else None,
            "end_reason": state.end_reason,
            "emotion": self._emotion_provider() if self._emotion_provider else None,
            "activity_constraints": dict(session.metadata.get("activity_constraints", {}))
            if isinstance(session.metadata.get("activity_constraints"), dict)
            else {},
        }
        return activity_manager.create_game_activity(
            session,
            goal="しりとりの現在ターンをルールに従って進行し、ゆららしく短く表現する",
            context_updates=context,
        )

    @staticmethod
    def _fallback_word(state: ShiritoriState) -> str | None:
        candidates = ("うみ", "みず", "たこ", "こあら", "らっぱ", "ぱんだ", "だるま")
        return next(
            (
                word
                for word in candidates
                if word not in state.used_words
                and (state.expected_head is None or word.startswith(state.expected_head))
            ),
            None,
        )

    def _write_ai_rejected(self, session: GameSession, retry_count: int, reason: str) -> None:
        self._trace_logger.warning(
            "shiritori:ai_word_rejected",
            session_id=session.session_id,
            retry_count=retry_count,
            validation_result=reason,
        )

    def _write_turn_advanced(
        self, session: GameSession, state: ShiritoriState, word: str | None
    ) -> None:
        self._trace_logger.info(
            "shiritori:turn_advanced",
            session_id=session.session_id,
            word=word,
            turn_count=state.turn_count,
            current_turn=state.current_turn.value,
            expected_head=state.expected_head,
        )
