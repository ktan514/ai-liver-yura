from __future__ import annotations

import asyncio
from typing import Any, cast

from app.adapters.obs.obs_error_mapper import ObsErrorMapper
from app.adapters.obs.obs_status_mapper import ObsStatusMapper
from app.adapters.obs.obs_websocket_client_factory import (
    ObsRequestClient,
    ObsWebSocketClientFactory,
)


class ObsWebSocketStreamingControlAdapter:
    """Write-capable OBS boundary, intentionally separate from PreparationPort."""

    adapter_type = "obs_websocket"

    def __init__(self, factory: ObsWebSocketClientFactory) -> None:
        self._factory = factory
        self._lock = asyncio.Lock()

    async def get_output_status(self) -> str:
        return cast(
            str,
            await self._call(
                lambda client: ObsStatusMapper.output_status(client.get_stream_status())
            ),
        )

    async def start_stream(self) -> None:
        async with self._lock:
            status = await self.get_output_status()
            if status in {"active", "starting"}:
                return
            if status != "idle":
                raise RuntimeError("stream.start.obs_invalid_state")
            await self._call(lambda client: client.start_stream())

    async def stop_stream(self) -> None:
        async with self._lock:
            status = await self.get_output_status()
            if status == "idle":
                return
            if status not in {"active", "starting", "stopping"}:
                raise RuntimeError("stream.stop.obs_invalid_state")
            await self._call(lambda client: client.stop_stream())

    async def _call(self, operation: Any) -> Any:
        try:
            return await asyncio.to_thread(self._with_client, operation)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise ObsErrorMapper.map(error) from error

    def _with_client(self, operation: Any) -> Any:
        client: ObsRequestClient | None = None
        try:
            client = self._factory.create()
            return operation(client)
        finally:
            if client is not None:
                client.disconnect()
