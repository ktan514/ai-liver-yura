from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from collections.abc import Generator

import uvicorn

from app.adapters.input import ConsoleInputReceiver
from app.admin_api import AdminApiService, create_admin_api
from app.admin_api.manual_check_log import create_manual_check_log
from app.config.app_config import load_app_config
from app.domain.events import AgentEvent, AgentEventType
from app.runtime import create_runtime_coordinator
from app.runtime.runtime_factory import (
    create_stream_preparation_runtime,
    create_streaming_demo_config,
)
from app.utils.trace import TraceLogger


def should_start_console_input(runtime_mode: str) -> bool:
    return runtime_mode != "streaming_demo"


def is_demo_exit_command(value: str) -> bool:
    return value.strip().lower() in {"exit", "quit"}


class CoordinatedUvicornServer(uvicorn.Server):
    """Leave process signals to the application-level shutdown coordinator."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        yield


async def wait_for_demo_shutdown(stop: asyncio.Event) -> None:
    """Watch only exit commands without enabling the normal console receiver."""
    loop = asyncio.get_running_loop()
    reader_installed = False

    def stdin_ready() -> None:
        line = sys.stdin.readline()
        if line == "":
            if reader_installed:
                loop.remove_reader(sys.stdin)
            return
        if is_demo_exit_command(line):
            stop.set()

    try:
        if sys.stdin.isatty() and hasattr(loop, "add_reader"):
            loop.add_reader(sys.stdin, stdin_ready)
            reader_installed = True
        await stop.wait()
    finally:
        if reader_installed:
            loop.remove_reader(sys.stdin)


async def async_main() -> None:
    config = load_app_config()
    if os.getenv("AI_LIVER_RUNTIME_MODE") == "streaming_demo":
        config = create_streaming_demo_config(config)
    TraceLogger.configure(
        level=config.trace.level,
        trace_file_path=config.trace.file_path,
        output_format=config.trace.format,
        max_bytes=config.trace.max_bytes,
        backup_count=config.trace.backup_count,
        timezone_name=config.trace.timezone,
        debug_file_enabled=config.trace.debug_file_enabled,
        debug_file_path=config.trace.debug_file_path,
        log_llm_prompts=config.trace.log_llm_prompts,
        log_llm_responses=config.trace.log_llm_responses,
        log_user_input=config.trace.log_user_input,
    )
    trace_logger = TraceLogger()
    trace_logger.info("app:start")
    trace_logger.info(
        "app:config_loaded",
        app_name=config.app.name,
        app_mode=config.app.mode,
        response_generator_type=config.response_generator.type,
    )
    runtime = create_runtime_coordinator(config)
    admin_host = os.getenv("AI_LIVER_ADMIN_API_HOST", "127.0.0.1")
    admin_token = os.getenv("AI_LIVER_ADMIN_API_TOKEN")
    if admin_host not in {"127.0.0.1", "localhost", "::1"} and not admin_token:
        raise RuntimeError("localhost以外へbindする場合はAI_LIVER_ADMIN_API_TOKENが必要です。")
    admin_runtime = create_stream_preparation_runtime(config)
    manual_check_log = create_manual_check_log(
        config.app.mode,
        os.getenv("AI_LIVER_MANUAL_CHECK_LOG") == "1",
    )
    admin_service = AdminApiService(
        admin_runtime,
        demo_mode=config.app.mode == "streaming_demo",
        manual_check_log=manual_check_log,
    )
    if manual_check_log is not None:
        manual_check_log.record("core", "runtime", "admin_api_started")
    admin_service.configure_opening(runtime)
    admin_server = CoordinatedUvicornServer(
        uvicorn.Config(
            create_admin_api(admin_service, admin_token),
            host=admin_host,
            port=int(os.getenv("AI_LIVER_ADMIN_API_PORT", "8765")),
            log_level="warning",
        )
    )
    trace_logger.info("app:runtime_created")
    streaming_demo = config.app.mode == "streaming_demo"
    console_receiver = (
        ConsoleInputReceiver() if should_start_console_input(config.app.mode) else None
    )
    trace_logger.write(
        "app:console_receiver_configured",
        enabled=console_receiver is not None,
        reason="disabled_in_streaming_demo" if streaming_demo else "console_mode",
    )

    runtime_task = asyncio.create_task(runtime.run())
    admin_task = asyncio.create_task(admin_server.serve())
    trace_logger.write("app:runtime_task_started")

    if not streaming_demo:
        await runtime.publish_event(
            AgentEvent(
                event_type=AgentEventType.APP_STARTED,
                payload={"source": "app_main"},
                priority=20,
                discardable=False,
            )
        )
        trace_logger.write("app:app_started_event_published")

    async def route_console_event(event: AgentEvent) -> None:
        if event.event_type == AgentEventType.USER_TEXT:
            await runtime.submit_user_text(
                str(event.payload.get("text") or ""),
                source=str(event.payload.get("source") or "console"),
            )
            return
        await runtime.publish_event(event)

    if console_receiver is None:
        print(
            "Streaming Demoを開始しました。"
            "終了するには quit / exit またはCtrl-Cを使用してください。"
        )
        shutdown_requested = asyncio.Event()
        loop = asyncio.get_running_loop()
        installed_signals: list[signal.Signals] = []
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, shutdown_requested.set)
                installed_signals.append(sig)
            except (NotImplementedError, RuntimeError):
                pass
        listener_task = asyncio.create_task(wait_for_demo_shutdown(shutdown_requested))
        done, _ = await asyncio.wait(
            {listener_task, admin_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if admin_task in done and not shutdown_requested.is_set():
            await admin_task
        shutdown_requested.set()
        await listener_task
        for sig in installed_signals:
            loop.remove_signal_handler(sig)
    else:
        print("コンソール入力デモを開始します。終了するには exit または quit を入力してください。")
        trace_logger.write("app:console_receiver_starting")
        await console_receiver.start(route_console_event)
        await console_receiver.wait_until_stopped()
        trace_logger.write("app:console_receiver_stopped")

    print("shutdown requested")
    admin_service.broker.publish("runtime.shutting_down", {})
    poller = admin_service._comment_poller  # noqa: SLF001 -- composition-root shutdown
    if poller is not None:
        poller.stop("runtime.shutting_down")
    print("poller stopped")
    admin_server.should_exit = True
    if not admin_task.done():
        await admin_task
    print("admin api stopped")
    trace_logger.write("app:runtime_stop_requested")
    runtime.stop()
    await runtime_task
    print("runtime stopped")
    trace_logger.write("app:runtime_task_finished")
    trace_logger.info("app:finished")
    if manual_check_log is not None:
        manual_check_log.close()
        print("manual log closed")
    print("終了しました。")


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        # Fallback for platforms where asyncio signal handlers are unavailable.
        pass


if __name__ == "__main__":
    main()
