from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


async def run_cancellable_blocking(
    function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    """blocking I/Oをdaemon threadで実行し、await側のcancelを即時反映する。"""

    loop = asyncio.get_running_loop()
    future: asyncio.Future[R] = loop.create_future()

    def finish_result(result: R) -> None:
        if not future.done():
            future.set_result(result)

    def finish_error(error: BaseException) -> None:
        if not future.done():
            future.set_exception(error)

    def run() -> None:
        try:
            result = function(*args, **kwargs)
        except BaseException as error:
            try:
                loop.call_soon_threadsafe(finish_error, error)
            except RuntimeError:
                return
        else:
            try:
                loop.call_soon_threadsafe(finish_result, result)
            except RuntimeError:
                return

    threading.Thread(
        target=run,
        name=f"blocking-io:{getattr(function, '__name__', 'call')}",
        daemon=True,
    ).start()
    return await future
