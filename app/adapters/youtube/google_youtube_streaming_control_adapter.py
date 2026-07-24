from __future__ import annotations

import asyncio
from typing import Any

from app.adapters.youtube.google_youtube_preparation_adapter import (
    GoogleYouTubePreparationAdapter,
)
from app.adapters.youtube.youtube_api_error_mapper import YouTubeApiErrorMapper


class GoogleYouTubeStreamingControlAdapter:
    """YouTube transition boundary; credentials and raw responses stay in Core."""

    adapter_type = "google"

    def __init__(
        self, client_factory: Any, reader: GoogleYouTubePreparationAdapter
    ) -> None:
        self._client_factory = client_factory
        self._reader = reader
        self._lock = asyncio.Lock()

    async def get_stream_status(self, stream_id: str) -> str:
        return await self._reader.get_stream_status(stream_id)

    async def get_broadcast_status(self, broadcast_id: str) -> str:
        return await self._reader.get_broadcast_status(broadcast_id)

    async def transition_broadcast_to_live(self, broadcast_id: str) -> None:
        async with self._lock:
            status = await self.get_broadcast_status(broadcast_id)
            if status == "live":
                return
            if status not in {"ready", "testing"}:
                raise RuntimeError("stream.start.broadcast_transition_failed")
            try:
                await asyncio.to_thread(self._transition_sync, broadcast_id)
            except Exception as error:
                raise YouTubeApiErrorMapper.map(error) from error

    async def transition_broadcast_to_complete(self, broadcast_id: str) -> None:
        async with self._lock:
            status = await self.get_broadcast_status(broadcast_id)
            if status == "complete":
                return
            if status != "live":
                raise RuntimeError("stream.end.broadcast_transition_failed")
            try:
                await asyncio.to_thread(self._transition_complete_sync, broadcast_id)
            except Exception as error:
                raise YouTubeApiErrorMapper.map(error) from error

    def _transition_complete_sync(self, broadcast_id: str) -> None:
        client = self._client_factory.create()
        (
            client.liveBroadcasts()
            .transition(broadcastStatus="complete", id=broadcast_id, part="id,status")
            .execute(num_retries=0)
        )

    def _transition_sync(self, broadcast_id: str) -> None:
        client = self._client_factory.create()
        (
            client.liveBroadcasts()
            .transition(broadcastStatus="live", id=broadcast_id, part="id,status")
            .execute(num_retries=0)
        )
