from __future__ import annotations

import asyncio
import threading

import pytest

from app.utils.async_blocking import run_cancellable_blocking


@pytest.mark.asyncio
async def test_cancel_does_not_wait_for_blocking_worker_thread() -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_call() -> str:
        started.set()
        release.wait()
        return "finished"

    task = asyncio.create_task(run_cancellable_blocking(blocking_call))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.2)
    release.set()
