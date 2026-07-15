from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.domain.games import GameDefinition, GameSession, GameSessionStatus
from app.utils.trace import TraceLogger


class GameEngine:
    """ゲーム定義の登録と、単一GameSessionのライフサイクルを管理する。"""

    def __init__(self, definitions: Iterable[GameDefinition] = ()) -> None:
        self._definitions: dict[str, GameDefinition] = {}
        self._current_session: GameSession | None = None
        self._lock = threading.RLock()
        self._trace_logger = TraceLogger()
        for definition in definitions:
            self.register_game(definition)

    def register_game(self, definition: GameDefinition) -> None:
        with self._lock:
            if definition.game_type in self._definitions:
                raise ValueError(f"ゲームは登録済みです: {definition.game_type}")
            self._definitions[definition.game_type] = definition
            self._trace_logger.info(
                "game_engine:game_registered",
                game_type=definition.game_type,
                display_name=definition.display_name,
                supported=definition.supported,
            )

    def list_supported_games(self) -> list[GameDefinition]:
        with self._lock:
            return [definition for definition in self._definitions.values() if definition.supported]

    def is_supported(self, game_type: str) -> bool:
        with self._lock:
            definition = self._definitions.get(game_type)
            return definition is not None and definition.supported

    def get_game_definition(self, game_type: str) -> GameDefinition:
        with self._lock:
            definition = self._definitions.get(game_type)
            if definition is None or not definition.supported:
                raise ValueError(f"未対応のゲームです: {game_type}")
            return definition

    def start_game(
        self,
        game_type: str,
        *,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> GameSession:
        with self._lock:
            definition = self._definitions.get(game_type)
            if definition is None or not definition.supported:
                self._trace_logger.warning(
                    "game_engine:start_rejected",
                    game_type=game_type,
                    reason="unsupported_game",
                )
                raise ValueError(f"未対応のゲームです: {game_type}")
            if self.get_active_session() is not None:
                self._trace_logger.warning(
                    "game_engine:start_rejected",
                    game_type=game_type,
                    session_id=self._current_session.session_id
                    if self._current_session is not None
                    else None,
                    reason="active_session_exists",
                )
                raise RuntimeError("別のゲームセッションが実行中です。")
            started_at = now or datetime.now(timezone.utc)
            initial_metadata = {
                **definition.create_initial_state(),
                **(metadata or {}),
            }
            starting = GameSession(
                game_type=game_type,
                status=GameSessionStatus.STARTING,
                started_at=started_at,
                updated_at=started_at,
                metadata=initial_metadata,
            )
            playing = starting.transition(GameSessionStatus.PLAYING, now=started_at)
            self._current_session = playing
            self._write_transition("game_engine:session_started", starting, playing)
            return playing

    def get_active_session(self) -> GameSession | None:
        with self._lock:
            if self._current_session is None:
                return None
            if self._current_session.status not in {
                GameSessionStatus.PLAYING,
                GameSessionStatus.PAUSED,
            }:
                return None
            return self._current_session

    def get_current_session(self) -> GameSession | None:
        """終了済みを含む、最後に管理したSessionを返す。"""

        with self._lock:
            return self._current_session

    def update_active_session(
        self,
        *,
        metadata: dict[str, Any],
        current_turn: int,
    ) -> GameSession:
        """ゲーム固有サービスが検証済み状態をSessionへ反映する。"""

        with self._lock:
            session = self._require_active_session()
            updated = replace(
                session,
                metadata=dict(metadata),
                current_turn=current_turn,
                updated_at=datetime.now(timezone.utc),
            )
            self._current_session = updated
            return updated

    def link_ongoing_activity(self, ongoing_activity_id: str) -> GameSession:
        """RuntimeのOngoingActivity IDをactive Sessionへ関連付ける。"""

        with self._lock:
            session = self._require_active_session()
            updated = replace(
                session,
                metadata={
                    **session.metadata,
                    "ongoing_activity_id": ongoing_activity_id,
                },
                updated_at=datetime.now(timezone.utc),
            )
            self._current_session = updated
            self._trace_logger.info(
                "game_engine:ongoing_activity_linked",
                session_id=updated.session_id,
                game_type=updated.game_type,
                ongoing_activity_id=ongoing_activity_id,
            )
            return updated

    def pause_game(self, *, reason: str = "pause_requested") -> GameSession:
        return self._transition_active(
            GameSessionStatus.PAUSED,
            label="game_engine:session_paused",
            reason=reason,
        )

    def resume_game(self, *, reason: str = "resume_requested") -> GameSession:
        with self._lock:
            session = self._require_current_session()
            if session.status != GameSessionStatus.PAUSED:
                raise RuntimeError(f"再開できないGameSession状態です: {session.status.value}")
            resumed = session.transition(GameSessionStatus.PLAYING)
            self._current_session = resumed
            self._write_transition("game_engine:session_resumed", session, resumed, reason=reason)
            return resumed

    def complete_game(
        self,
        result: dict[str, Any],
        *,
        reason: str = "game_completed",
    ) -> GameSession:
        return self._transition_active(
            GameSessionStatus.COMPLETED,
            label="game_engine:session_completed",
            reason=reason,
            result=result,
        )

    def cancel_game(self, reason: str) -> GameSession:
        return self._transition_active(
            GameSessionStatus.CANCELED,
            label="game_engine:session_canceled",
            reason=reason,
        )

    def _transition_active(
        self,
        new_status: GameSessionStatus,
        *,
        label: str,
        reason: str,
        result: dict[str, Any] | None = None,
    ) -> GameSession:
        with self._lock:
            session = self._require_active_session()
            transitioned = session.transition(
                new_status,
                result=result,
                end_reason=reason
                if new_status in {GameSessionStatus.COMPLETED, GameSessionStatus.CANCELED}
                else None,
            )
            self._current_session = transitioned
            self._write_transition(label, session, transitioned, reason=reason)
            return transitioned

    def _require_active_session(self) -> GameSession:
        session = self.get_active_session()
        if session is None:
            raise RuntimeError("activeなGameSessionがありません。")
        return session

    def _require_current_session(self) -> GameSession:
        if self._current_session is None:
            raise RuntimeError("GameSessionがありません。")
        return self._current_session

    def _write_transition(
        self,
        label: str,
        previous: GameSession,
        current: GameSession,
        *,
        reason: str | None = None,
    ) -> None:
        self._trace_logger.info(
            label,
            session_id=current.session_id,
            game_type=current.game_type,
            previous_status=previous.status.value,
            new_status=current.status.value,
            reason=reason,
        )
