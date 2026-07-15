from __future__ import annotations

import json
import re

from app.domain.activities import Activity, ActivityType
from app.domain.games import (
    GameControl,
    GameInputClassification,
    GameInputClassificationResult,
    GameSession,
    ShiritoriPlayer,
    ShiritoriState,
    get_shiritori_head,
    normalize_shiritori_word,
)
from app.ports.response_generator import ResponseGenerator
from app.runtime.game_engine import GameEngine
from app.utils.trace import TraceLogger


class GameInputClassifier:
    """決定論的判定を優先し、曖昧な場合だけLLMへ分類を依頼する。"""

    _control_patterns: tuple[tuple[GameControl, tuple[str, ...]], ...] = (
        (GameControl.RESTART, ("最初から", "やり直", "リスタート")),
        (GameControl.SURRENDER, ("降参", "まけた", "負けた")),
        (GameControl.PAUSE, ("ちょっと待って", "待って", "一時停止")),
        (GameControl.RESUME, ("再開", "続けよう", "続きやろう")),
        (GameControl.QUIT, ("やめよう", "やめる", "終了", "終わろう")),
    )
    _game_chat_markers = ("しりとり", "単語", "何の文字", "ずる", "その言葉", "楽しい")
    _ambiguous_phrases = ("それでいいよ", "もういい", "次どうする", "こっちかな")
    _unsupported_names = ("将棋", "チェス", "ポーカー", "オセロ", "囲碁")
    _start_intent_patterns = (
        r"しよ(?:う|ー|っ|っか|っよ)?",
        r"しましょ(?:う)?",
        r"しませんか",
        r"やろ(?:う|ー)?",
        r"やりたい",
        r"遊ぼ(?:う|ー)?",
        r"遊びたい",
    )
    _vague_game_start_markers = (
        "ゲームでも",
        "一緒に遊ば",
        "言葉をつなぐ",
        "言葉を繋ぐ",
    )

    def __init__(
        self,
        game_engine: GameEngine,
        response_generator: ResponseGenerator | None = None,
    ) -> None:
        self._game_engine = game_engine
        self._response_generator = response_generator
        self._trace_logger = TraceLogger()

    async def classify(self, text: str) -> GameInputClassificationResult:
        session = self._game_engine.get_active_session()
        deterministic = self._classify_deterministically(text, session)
        if deterministic is not None:
            self._write_classified(deterministic, "game_input_classifier:deterministic_match")
            if deterministic.classification == GameInputClassification.GAME_START_REQUEST:
                self._write_classified(deterministic, "game_start_classifier:deterministic_match")
                self._write_classified(deterministic, "game_start_classifier:classified")
            return deterministic
        if self._response_generator is None:
            return self._fallback(text, session, "llm_classifier_not_configured")

        self._trace_logger.debug(
            "game_input_classifier:llm_requested",
            game_type=session.game_type if session else None,
            current_turn=self._current_turn(session),
        )
        if session is None and self._is_vague_game_start_candidate(text):
            self._trace_logger.debug(
                "game_start_classifier:llm_requested",
                supported_games=[
                    game.game_type for game in self._game_engine.list_supported_games()
                ],
            )
        activity = Activity(
            activity_type=ActivityType.GAME_INPUT_CLASSIFICATION,
            goal="ユーザー入力をゲーム入力または会話へ分類する",
            context=self._classification_context(text, session),
        )
        try:
            raw_output = await self._response_generator.generate_response(activity)
            result = self.parse_llm_output(raw_output, text=text, session=session)
        except Exception as error:
            self._trace_logger.warning(
                "game_input_classifier:llm_failed",
                game_type=session.game_type if session else None,
                error_type=type(error).__name__,
                reason="llm_call_failed",
            )
            fallback = self._fallback(text, session, "llm_call_failed")
            if session is None and self._is_vague_game_start_candidate(text):
                self._write_classified(fallback, "game_start_classifier:fallback")
            return fallback
        if result is None:
            self._trace_logger.warning(
                "game_input_classifier:llm_failed",
                game_type=session.game_type if session else None,
                reason="invalid_structured_output",
            )
            fallback = self._fallback(text, session, "invalid_structured_output")
            if session is None and self._is_vague_game_start_candidate(text):
                self._write_classified(fallback, "game_start_classifier:fallback")
            return fallback
        self._write_classified(result, "game_input_classifier:llm_succeeded")
        if result.classification == GameInputClassification.GAME_START_REQUEST:
            self._write_classified(result, "game_start_classifier:classified")
        return result

    def _classify_deterministically(
        self, text: str, session: GameSession | None
    ) -> GameInputClassificationResult | None:
        stripped = text.strip()
        normalized = normalize_shiritori_word(stripped.replace("しり取り", "しりとり"))
        requested_game = self._unsupported_game_request(stripped)
        if requested_game is not None and not self._game_engine.is_supported(requested_game):
            return self._result(
                GameInputClassification.UNSUPPORTED_GAME_REQUEST,
                stripped,
                session,
                confidence=0.99,
                requested_game=requested_game,
                reason="requested_game_not_supported",
            )
        if "しりとり" in normalized and self._has_start_intent(normalized):
            if session is None:
                return self._result(
                    GameInputClassification.GAME_START_REQUEST,
                    stripped,
                    None,
                    confidence=0.99,
                    requested_game="shiritori",
                    reason="explicit_supported_game_start_request",
                )
            return self._result(
                GameInputClassification.AMBIGUOUS,
                stripped,
                session,
                confidence=0.95,
                requested_game="shiritori",
                chat_text=stripped,
                reason="supported_game_already_active",
            )
        if session is None:
            if any(marker in stripped for marker in self._vague_game_start_markers):
                return None
            return self._result(
                GameInputClassification.NORMAL_CHAT,
                stripped,
                None,
                confidence=1.0,
                chat_text=stripped,
                reason="no_active_game_session",
            )
        for control, markers in self._control_patterns:
            if any(marker in stripped for marker in markers):
                return self._result(
                    GameInputClassification.GAME_CONTROL,
                    stripped,
                    session,
                    confidence=0.98,
                    game_control=control,
                    reason="explicit_game_control_phrase",
                )
        mixed = self._split_mixed(stripped, session)
        if mixed is not None:
            word, chat_text = mixed
            return self._result(
                GameInputClassification.MIXED,
                stripped,
                session,
                confidence=0.96,
                game_word=word,
                chat_text=chat_text,
                reason="game_word_and_chat_detected",
            )
        if any(phrase in stripped for phrase in self._ambiguous_phrases):
            return self._result(
                GameInputClassification.AMBIGUOUS,
                stripped,
                session,
                confidence=0.55,
                chat_text=stripped,
                reason="ambiguous_short_phrase",
            )
        if any(marker in stripped for marker in self._game_chat_markers) and (
            "?" in stripped or "？" in stripped or len(stripped) > 6
        ):
            return self._result(
                GameInputClassification.GAME_CHAT,
                stripped,
                session,
                confidence=0.94,
                chat_text=stripped,
                reason="comment_or_question_about_game",
            )
        state = self._shiritori_state(session)
        normalized = normalize_shiritori_word(stripped)
        is_single_word = bool(normalized) and re.fullmatch(r"[ぁ-ゖー]+", normalized) is not None
        if (
            state is not None
            and state.current_turn == ShiritoriPlayer.USER
            and is_single_word
            and (
                state.expected_head is None or get_shiritori_head(normalized) == state.expected_head
            )
        ):
            return self._result(
                GameInputClassification.GAME_MOVE,
                stripped,
                session,
                confidence=0.97,
                game_word=normalized,
                reason="single_word_matches_expected_head",
            )
        if "?" in stripped or "？" in stripped or stripped.endswith(("ね", "よ", "だね")):
            return self._result(
                GameInputClassification.NORMAL_CHAT,
                stripped,
                session,
                confidence=0.9,
                chat_text=stripped,
                reason="ordinary_conversation_expression",
            )
        return None

    def parse_llm_output(
        self,
        raw_output: str,
        *,
        text: str,
        session: GameSession | None,
    ) -> GameInputClassificationResult | None:
        try:
            value = json.loads(raw_output.strip())
        except json.JSONDecodeError:
            return None
        if not isinstance(value, dict):
            return None
        try:
            classification = GameInputClassification(value.get("classification"))
        except (ValueError, TypeError):
            return None
        confidence = value.get("confidence")
        if not isinstance(confidence, (int, float)):
            return None
        game_word = value.get("game_word")
        chat_text = value.get("chat_text")
        requested_game = value.get("requested_game")
        control_value = value.get("game_control")
        try:
            control = GameControl(control_value) if control_value is not None else None
        except ValueError:
            return None
        if classification == GameInputClassification.GAME_MOVE and not isinstance(game_word, str):
            return None
        if classification == GameInputClassification.MIXED and (
            not isinstance(game_word, str) or not isinstance(chat_text, str)
        ):
            return None
        if classification == GameInputClassification.GAME_CONTROL and control is None:
            return None
        if classification == GameInputClassification.UNSUPPORTED_GAME_REQUEST and not isinstance(
            requested_game, str
        ):
            return None
        if classification == GameInputClassification.GAME_START_REQUEST and not isinstance(
            requested_game, str
        ):
            return None
        return self._result(
            classification,
            text,
            session,
            confidence=float(confidence),
            classifier_type="llm",
            game_word=game_word if isinstance(game_word, str) else None,
            game_control=control,
            chat_text=chat_text if isinstance(chat_text, str) else None,
            requested_game=requested_game if isinstance(requested_game, str) else None,
            reason=str(value.get("reason") or "llm_classification"),
        )

    def _fallback(
        self, text: str, session: GameSession | None, reason: str
    ) -> GameInputClassificationResult:
        result = self._result(
            GameInputClassification.AMBIGUOUS,
            text,
            session,
            confidence=0.0,
            classifier_type="fallback",
            chat_text=text,
            reason=reason,
        )
        self._write_classified(result, "game_input_classifier:fallback")
        return result

    def _result(
        self,
        classification: GameInputClassification,
        text: str,
        session: GameSession | None,
        *,
        confidence: float,
        classifier_type: str = "deterministic",
        game_word: str | None = None,
        game_control: GameControl | None = None,
        chat_text: str | None = None,
        requested_game: str | None = None,
        reason: str,
    ) -> GameInputClassificationResult:
        return GameInputClassificationResult(
            classification=classification,
            confidence=max(0.0, min(1.0, confidence)),
            raw_text=text,
            classifier_type=classifier_type,
            game_type=session.game_type if session else None,
            game_word=game_word,
            game_control=game_control,
            chat_text=chat_text,
            requested_game=requested_game,
            reason=reason,
            session_id=session.session_id if session else None,
            session_status=session.status.value if session else None,
        )

    def _split_mixed(self, text: str, session: GameSession) -> tuple[str, str] | None:
        state = self._shiritori_state(session)
        if state is None or state.current_turn != ShiritoriPlayer.USER:
            return None
        parts = re.split(r"[。！!]", text, maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            return None
        candidate = normalize_shiritori_word(parts[0])
        if not candidate or (
            state.expected_head is not None and get_shiritori_head(candidate) != state.expected_head
        ):
            return None
        return candidate, parts[1].strip()

    @staticmethod
    def _shiritori_state(session: GameSession | None) -> ShiritoriState | None:
        if session is None or session.game_type != "shiritori":
            return None
        state = session.metadata.get("shiritori_state")
        return state if isinstance(state, ShiritoriState) else None

    @staticmethod
    def _current_turn(session: GameSession | None) -> str | None:
        state = GameInputClassifier._shiritori_state(session)
        return state.current_turn.value if state else None

    def _classification_context(self, text: str, session: GameSession | None) -> dict[str, object]:
        state = self._shiritori_state(session)
        return {
            "user_text": text,
            "game_type": session.game_type if session else None,
            "game_status": session.status.value if session else None,
            "game_session_id": session.session_id if session else None,
            "current_turn": state.current_turn.value if state else None,
            "last_word": state.last_word if state else None,
            "expected_head": state.expected_head if state else None,
            "supported_games": [
                game.game_type for game in self._game_engine.list_supported_games()
            ],
        }

    def _unsupported_game_request(self, text: str) -> str | None:
        if not self._has_start_intent(text):
            return None
        return next((name for name in self._unsupported_names if name in text), None)

    def _has_start_intent(self, text: str) -> bool:
        return any(re.search(pattern, text) for pattern in self._start_intent_patterns)

    def _is_vague_game_start_candidate(self, text: str) -> bool:
        return any(marker in text for marker in self._vague_game_start_markers)

    def _write_classified(self, result: GameInputClassificationResult, label: str) -> None:
        self._trace_logger.info(
            label,
            classification=result.classification.value,
            confidence=result.confidence,
            game_type=result.game_type,
            classifier_type=result.classifier_type,
            current_turn=self._current_turn(self._game_engine.get_active_session()),
            reason=result.reason,
            game_engine_instance_id=id(self._game_engine),
        )
