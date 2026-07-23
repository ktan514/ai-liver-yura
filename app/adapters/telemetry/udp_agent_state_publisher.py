from __future__ import annotations

import json
import socket
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.runtime.agent_state import AgentState


class DatagramSocket(Protocol):
    def sendto(self, data: bytes, address: tuple[str, int]) -> int: ...


@dataclass(frozen=True, slots=True)
class UdpAgentStatePublisherConfig:
    host: str = "127.0.0.1"
    port: int = 8766
    enabled: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("telemetry portは1以上65535以下にしてください。")


class UdpAgentStatePublisher:
    """機密性のある本文を除外し、内面状態だけをlocalhostへ配信する。"""

    def __init__(
        self,
        config: UdpAgentStatePublisherConfig | None = None,
        *,
        socket_factory: Callable[[], DatagramSocket] | None = None,
    ) -> None:
        self._config = config or UdpAgentStatePublisherConfig()
        self._socket = (socket_factory or self._create_socket)()

    @staticmethod
    def _create_socket() -> DatagramSocket:
        return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def publish(self, state: AgentState) -> None:
        if not self._config.enabled:
            return
        payload = {
            "schema_version": 1,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "emotion": {
                **asdict(state.current_emotion),
                "mood": state.current_emotion.mood.value,
            },
            "drive": asdict(state.current_drive),
            "activity": {
                "type": (
                    state.active_activity.activity_type.value
                    if state.active_activity is not None
                    else None
                ),
                "active": state.active_activity is not None,
                "pending_count": len(state.pending_activities),
            },
            "attention": {"engaged": state.attention_target is not None},
            "stream": {"status": state.stream_status},
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            self._socket.sendto(encoded, (self._config.host, self._config.port))
        except OSError:
            # 可視化は観測専用であり、停止していても本体の状態更新を妨げない。
            return
