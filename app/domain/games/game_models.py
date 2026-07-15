from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4


class GameSessionStatus(str, Enum):
    STARTING = "starting"
    PLAYING = "playing"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELED = "canceled"


_ALLOWED_TRANSITIONS: dict[GameSessionStatus, set[GameSessionStatus]] = {
    GameSessionStatus.STARTING: {GameSessionStatus.PLAYING, GameSessionStatus.CANCELED},
    GameSessionStatus.PLAYING: {
        GameSessionStatus.PAUSED,
        GameSessionStatus.COMPLETED,
        GameSessionStatus.CANCELED,
    },
    GameSessionStatus.PAUSED: {
        GameSessionStatus.PLAYING,
        GameSessionStatus.CANCELED,
    },
    GameSessionStatus.COMPLETED: set(),
    GameSessionStatus.CANCELED: set(),
}


@dataclass(frozen=True, slots=True)
class GameSession:
    game_type: str
    status: GameSessionStatus
    started_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str = field(default_factory=lambda: str(uuid4()))
    ended_at: datetime | None = None
    current_turn: int = 0
    result: dict[str, Any] | None = None
    end_reason: str | None = None

    def transition(
        self,
        new_status: GameSessionStatus,
        *,
        now: datetime | None = None,
        result: dict[str, Any] | None = None,
        end_reason: str | None = None,
    ) -> GameSession:
        if new_status not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(
                f"不正なGameSession状態遷移です: {self.status.value} -> {new_status.value}"
            )
        changed_at = now or datetime.now(timezone.utc)
        ended_at = (
            changed_at
            if new_status in {GameSessionStatus.COMPLETED, GameSessionStatus.CANCELED}
            else None
        )
        return replace(
            self,
            status=new_status,
            updated_at=changed_at,
            ended_at=ended_at,
            result=result if result is not None else self.result,
            end_reason=end_reason,
        )


class GameDefinition(Protocol):
    game_type: str
    display_name: str
    description: str
    supported: bool

    def create_initial_state(self) -> dict[str, Any]: ...
