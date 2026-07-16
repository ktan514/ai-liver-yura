from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar
from uuid import uuid4

from app.domain.streaming import StreamPreparationCommand, StreamPreparationResult
from app.usecases import PrepareStreamSessionUsecase

T = TypeVar("T")


class RuntimeCommandGateway:
    """Qt Threadから専用asyncio loopへCommandを安全に送る境界。"""

    def __init__(self, usecase: PrepareStreamSessionUsecase) -> None:
        self._usecase = usecase
        self._loop = asyncio.new_event_loop()
        self._started = threading.Event()
        self._closed = False
        self._session_id: str | None = None
        self._thread = threading.Thread(
            target=self._run_loop, name="stream-preparation-runtime", daemon=True
        )
        self._thread.start()
        self._started.wait(timeout=5)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()

    def list_broadcasts(self) -> concurrent.futures.Future[object]:
        return self._submit(self._usecase.list_broadcasts())

    def youtube_adapter_type(self) -> concurrent.futures.Future[object]:
        async def get_adapter_type() -> object:
            return self._usecase.youtube_adapter_type

        return self._submit(get_adapter_type())

    def youtube_authentication_state(self) -> concurrent.futures.Future[object]:
        return self._submit(self._usecase.get_youtube_authentication_state())

    def authenticate_youtube(self) -> concurrent.futures.Future[object]:
        return self._submit(self._usecase.authenticate_youtube())

    def list_run_of_shows(self) -> concurrent.futures.Future[object]:
        async def load() -> object:
            return await asyncio.to_thread(self._usecase.list_run_of_shows)

        return self._submit(load())

    def prepare(
        self,
        *,
        broadcast_id: str,
        broadcast_title: str,
        run_of_show_id: str,
        requested_by: str = "pyqt_management_ui",
    ) -> concurrent.futures.Future[StreamPreparationResult]:
        async def execute() -> StreamPreparationResult:
            session = (
                self._usecase.get_session(self._session_id)
                if self._session_id is not None
                else self._usecase.find_active_session()
            )
            trace_id = str(uuid4())
            if session is None:
                from app.domain.streaming import YouTubeBroadcastSummary

                session = self._usecase.create_session(
                    YouTubeBroadcastSummary(broadcast_id, broadcast_title),
                    trace_id=trace_id,
                    run_of_show_id=run_of_show_id,
                )
                self._session_id = session.session_id
            elif session.selected_broadcast_id != broadcast_id:
                raise RuntimeError("別の配信枠のStreamSessionが既に存在します。")
            command = StreamPreparationCommand(
                command_id=str(uuid4()),
                trace_id=trace_id,
                session_id=session.session_id,
                selected_broadcast_id=broadcast_id,
                requested_by=requested_by,
                expected_state_version=session.state_version,
                run_of_show_id=run_of_show_id,
            )
            return await self._usecase.execute(command)

        return self._submit(execute())

    def _submit(self, coroutine: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
        if self._closed:
            coroutine.close()
            raise RuntimeError("RuntimeCommandGatewayは終了済みです。")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    @property
    def thread_id(self) -> int | None:
        return self._thread.ident
