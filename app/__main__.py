from __future__ import annotations

import asyncio

from app.adapters.input import ConsoleInputReceiver
from app.bootstrap.runtime import create_runtime_coordinator
from app.config.app_config import load_app_config
from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.utils.trace import TraceLogger


def should_start_console_input(_runtime_mode: str) -> bool:
    """The core process always exposes its trusted local operator input."""

    return True


def is_demo_exit_command(value: str) -> bool:
    """Compatibility helper for callers that still provide a terminal loop."""

    return value.strip().lower() in {"exit", "quit"}


async def async_main() -> None:
    """Run Yura's core without composing OBS or YouTube operations."""

    config = load_app_config()
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
    trace_logger.info(
        "app:start",
        app_name=config.app.name,
        app_mode=config.app.mode,
        response_generator_type=config.response_generator.type,
    )
    runtime = create_runtime_coordinator(config)
    receiver = ConsoleInputReceiver()
    runtime_task = asyncio.create_task(runtime.run())

    await runtime.publish_event(
        AgentEvent(
            event_type=AgentEventType.APP_STARTED,
            payload={"source": "app_main"},
            priority=20,
            discardable=False,
            authority=InputAuthority.SYSTEM,
        )
    )

    async def route_console_event(event: AgentEvent) -> None:
        if event.event_type == AgentEventType.USER_TEXT:
            await runtime.submit_user_text(
                str(event.payload.get("text") or ""),
                source="console",
                authority=event.authority,
            )
            return
        await runtime.publish_event(event)

    print("ゆらを起動しました。管理者として自然文で指示できます。終了: exit / quit")
    try:
        await receiver.start(route_console_event)
        await receiver.wait_until_stopped()
    finally:
        await receiver.stop()
        runtime.stop()
        await runtime_task
        trace_logger.info("app:finished")
        print("終了しました。")


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
