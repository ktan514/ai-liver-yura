from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class FakeObsStreamingControlAdapter:
    statuses: list[str] = field(default_factory=lambda: ["idle", "active", "active"])
    adapter_type: str = "fake"
    start_calls: int = 0
    stop_calls: int = 0

    async def start_stream(self) -> None:
        self.start_calls += 1

    async def get_output_status(self) -> str:
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    async def stop_stream(self) -> None:
        self.stop_calls += 1


@dataclass(slots=True)
class FakeYouTubeStreamingControlAdapter:
    stream_statuses: list[str] = field(default_factory=lambda: ["active", "active"])
    broadcast_statuses: list[str] = field(default_factory=lambda: ["ready", "live", "live"])
    adapter_type: str = "fake"
    transition_calls: int = 0
    complete_calls: int = 0

    async def get_stream_status(self, stream_id: str) -> str:
        del stream_id
        return (
            self.stream_statuses.pop(0)
            if len(self.stream_statuses) > 1
            else self.stream_statuses[0]
        )

    async def transition_broadcast_to_live(self, broadcast_id: str) -> None:
        del broadcast_id
        self.transition_calls += 1

    async def transition_broadcast_to_complete(self, broadcast_id: str) -> None:
        del broadcast_id
        self.complete_calls += 1

    async def get_broadcast_status(self, broadcast_id: str) -> str:
        del broadcast_id
        return (
            self.broadcast_statuses.pop(0)
            if len(self.broadcast_statuses) > 1
            else self.broadcast_statuses[0]
        )
