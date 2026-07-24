from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.adapters.obs.obs_error_mapper import ObsAdapterError, ObsErrorMapper
from app.adapters.obs.obs_status_mapper import ObsStatusMapper
from app.adapters.obs.obs_websocket_client_factory import (
    ObsRequestClient,
    ObsWebSocketClientFactory,
)

logger = logging.getLogger(__name__)


class ObsWebSocketStreamingControlAdapter:
    """Persistent, serialized OBS WebSocket 5.x streaming control boundary."""

    adapter_type = "obs_websocket"

    def __init__(
        self,
        factory: ObsWebSocketClientFactory,
        *,
        request_timeout_seconds: float = 5.0,
        state_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        if min(request_timeout_seconds, state_timeout_seconds) <= 0:
            raise ValueError("OBS timeouts must be positive")
        if poll_interval_seconds < 0:
            raise ValueError("OBS poll interval must not be negative")
        self._factory = factory
        self._request_timeout = request_timeout_seconds
        self._state_timeout = state_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="obs-control"
        )
        self._client: ObsRequestClient | None = None
        self._connection_status = "disconnected"
        self._closed = False

    async def connect(self) -> None:
        async with self._lock:
            await self._connect_locked()

    async def disconnect(self) -> None:
        async with self._lock:
            if self._closed:
                return
            client = self._client
            self._client = None
            self._connection_status = "disconnected"
            if client is not None:
                try:
                    await self._execute(lambda: client.disconnect())
                except Exception as error:
                    logger.info(
                        "OBS disconnect completed with mapped error: %s",
                        ObsErrorMapper.map(error),
                    )
            self._closed = True
            logger.info("OBS disconnected")
        self._executor.shutdown(wait=True, cancel_futures=True)

    async def get_connection_status(self) -> str:
        return self._connection_status

    async def get_output_status(self) -> str:
        async with self._lock:
            return await self._status_locked()

    async def start_stream(self) -> None:
        async with self._lock:
            status = await self._status_locked()
            if status == "active":
                return
            if status not in {"idle", "starting"}:
                raise ObsAdapterError("start_rejected", "obs.stream_start_rejected")
            if status == "idle":
                logger.info("OBS stream start requested")
                await self._request_locked(lambda client: client.start_stream())
            await self._wait_for_status_locked("active", "obs.stream_start_timeout")
            logger.info("OBS stream active confirmed")

    async def stop_stream(self) -> None:
        async with self._lock:
            status = await self._status_locked()
            if status == "idle":
                return
            if status not in {"active", "starting", "stopping"}:
                raise ObsAdapterError("stop_rejected", "obs.stream_stop_rejected")
            if status != "stopping":
                logger.info("OBS stream stop requested")
                await self._request_locked(lambda client: client.stop_stream())
            await self._wait_for_status_locked("idle", "obs.stream_stop_timeout")
            logger.info("OBS stream inactive confirmed")

    async def _connect_locked(self) -> None:
        if self._client is not None:
            return
        if self._closed:
            raise ObsAdapterError("lifecycle", "obs.adapter_closed")
        self._connection_status = "connecting"
        logger.info("OBS connection starting")
        try:
            self._client = await self._execute(self._factory.create)
        except Exception as error:
            self._connection_status = "error"
            mapped = ObsErrorMapper.map(error)
            logger.info("OBS connection failed: %s", mapped)
            raise mapped from error
        self._connection_status = "connected"
        logger.info("OBS connection established")

    async def _status_locked(self) -> str:
        response = await self._request_locked(lambda client: client.get_stream_status())
        return ObsStatusMapper.output_status(response)

    async def _wait_for_status_locked(self, expected: str, failure_code: str) -> None:
        deadline = asyncio.get_running_loop().time() + self._state_timeout
        while True:
            status = await self._status_locked()
            if status == expected:
                return
            if status in {"failed", "unknown"}:
                raise ObsAdapterError("request_failed", failure_code)
            if asyncio.get_running_loop().time() >= deadline:
                raise ObsAdapterError("timeout", failure_code, True)
            await asyncio.sleep(self._poll_interval)

    async def _request_locked(
        self, operation: Callable[[ObsRequestClient], Any]
    ) -> Any:
        await self._connect_locked()
        client = self._client
        assert client is not None
        try:
            return await self._execute(lambda: operation(client))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            mapped = ObsErrorMapper.map(error)
            if mapped.category in {"network", "connection_refused", "authentication"}:
                self._client = None
                self._connection_status = "disconnected"
            logger.info("OBS request failed: %s", mapped)
            raise mapped from error

    async def _execute(self, operation: Callable[[], Any]) -> Any:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self._executor, operation),
                timeout=self._request_timeout,
            )
        except asyncio.TimeoutError as error:
            raise ObsAdapterError("timeout", "obs.request_timeout", True) from error
