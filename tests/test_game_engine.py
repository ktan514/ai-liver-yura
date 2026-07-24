from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from app.plugins.games.engine import GameEngine
from app.plugins.games.session import GameSessionStatus


@dataclass(frozen=True)
class FakeGameDefinition:
    game_type: str = "fake_game"
    display_name: str = "Fake Game"
    description: str = "テスト用ゲーム"
    supported: bool = True

    def create_initial_state(self) -> dict[str, Any]:
        return {"board": [], "player": "user"}


def test_register_and_list_supported_game() -> None:
    definition = FakeGameDefinition()
    engine = GameEngine()

    engine.register_game(definition)

    assert engine.is_supported("fake_game") is True
    assert engine.is_supported("unknown") is False
    assert engine.list_supported_games() == [definition]
    assert engine.get_game_definition("fake_game") is definition


def test_duplicate_game_registration_is_rejected() -> None:
    engine = GameEngine((FakeGameDefinition(),))

    with pytest.raises(ValueError, match="登録済み"):
        engine.register_game(FakeGameDefinition())


def test_unsupported_definition_is_not_listed_or_startable() -> None:
    engine = GameEngine((FakeGameDefinition(supported=False),))

    assert engine.list_supported_games() == []
    assert engine.is_supported("fake_game") is False
    with pytest.raises(ValueError, match="未対応"):
        engine.start_game("fake_game")


def test_start_supported_game_creates_playing_session() -> None:
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    engine = GameEngine((FakeGameDefinition(),))

    session = engine.start_game("fake_game", now=now)

    assert session.session_id
    assert session.game_type == "fake_game"
    assert session.status == GameSessionStatus.PLAYING
    assert session.started_at == now
    assert session.updated_at == now
    assert session.current_turn == 0
    assert session.metadata == {"board": [], "player": "user"}
    assert engine.get_active_session() == session


def test_start_rejects_unsupported_and_duplicate_active_session() -> None:
    engine = GameEngine((FakeGameDefinition(),))

    with pytest.raises(ValueError, match="未対応"):
        engine.start_game("unknown")

    engine.start_game("fake_game")
    with pytest.raises(RuntimeError, match="実行中"):
        engine.start_game("fake_game")


def test_pause_and_resume_game() -> None:
    engine = GameEngine((FakeGameDefinition(),))
    playing = engine.start_game("fake_game")

    paused = engine.pause_game(reason="user_interruption")
    resumed = engine.resume_game(reason="conversation_finished")

    assert paused.session_id == playing.session_id
    assert paused.status == GameSessionStatus.PAUSED
    assert resumed.status == GameSessionStatus.PLAYING
    assert engine.get_active_session() == resumed


def test_complete_game_removes_session_from_active_session() -> None:
    engine = GameEngine((FakeGameDefinition(),))
    engine.start_game("fake_game")

    completed = engine.complete_game({"winner": "user"}, reason="normal_end")

    assert completed.status == GameSessionStatus.COMPLETED
    assert completed.result == {"winner": "user"}
    assert completed.end_reason == "normal_end"
    assert completed.ended_at is not None
    assert engine.get_active_session() is None
    with pytest.raises(RuntimeError, match="再開できない"):
        engine.resume_game()


@pytest.mark.parametrize("pause_first", [False, True])
def test_cancel_game_from_playing_or_paused(pause_first: bool) -> None:
    engine = GameEngine((FakeGameDefinition(),))
    engine.start_game("fake_game")
    if pause_first:
        engine.pause_game()

    canceled = engine.cancel_game("user_requested")

    assert canceled.status == GameSessionStatus.CANCELED
    assert canceled.end_reason == "user_requested"
    assert engine.get_active_session() is None
    with pytest.raises(RuntimeError, match="再開できない"):
        engine.resume_game()


@pytest.mark.parametrize("operation", ["pause", "complete", "cancel"])
def test_operation_without_active_session_is_rejected(operation: str) -> None:
    engine = GameEngine((FakeGameDefinition(),))

    with pytest.raises(RuntimeError, match="activeなGameSession"):
        if operation == "pause":
            engine.pause_game()
        elif operation == "complete":
            engine.complete_game({})
        else:
            engine.cancel_game("test")


def test_completed_session_rejects_direct_transition_to_playing() -> None:
    engine = GameEngine((FakeGameDefinition(),))
    engine.start_game("fake_game")
    completed = engine.complete_game({})

    with pytest.raises(ValueError, match="不正なGameSession状態遷移"):
        completed.transition(GameSessionStatus.PLAYING)
