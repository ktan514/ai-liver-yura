from __future__ import annotations

import json

from app.adapters.telemetry import (
    UdpAgentStatePublisher,
    UdpAgentStatePublisherConfig,
)
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType
from app.runtime.agent_state import AgentState


class CapturingSocket:
    def __init__(self) -> None:
        self.datagrams: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.datagrams.append((data, address))
        return len(data)


def test_udp_agent_state_publisher_excludes_text_and_emits_inner_state() -> None:
    transport = CapturingSocket()
    publisher = UdpAgentStatePublisher(
        UdpAgentStatePublisherConfig(port=18766),
        socket_factory=lambda: transport,
    )
    state = AgentState(
        current_emotion=EmotionState(
            mood=MoodType.HAPPY,
            arousal=0.7,
            valence=0.6,
            talkativeness=0.4,
        ),
        current_drive=DriveState(
            curiosity=0.8,
            engagement=0.5,
            boredom=0.1,
            energy=0.9,
        ),
        attention_target="sensitive-window-title",
    )

    publisher.publish(state)

    raw, address = transport.datagrams[0]
    payload = json.loads(raw)
    assert address == ("127.0.0.1", 18766)
    assert payload["emotion"]["mood"] == "happy"
    assert payload["drive"]["curiosity"] == 0.8
    assert payload["attention"] == {"engaged": True}
    assert "sensitive-window-title" not in raw.decode("utf-8")
