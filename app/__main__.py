from __future__ import annotations

import asyncio

from app.adapters.input import ConsoleInputReceiver
from app.config.app_config import load_app_config
from app.common.trace import TraceLogger
from app.domain.events import AgentEvent, AgentEventType
from app.runtime import create_runtime_coordinator


async def async_main() -> None:
    trace_logger = TraceLogger()
    trace_logger.write("app:start")
    config = load_app_config()
    trace_logger.write(
        "app:config_loaded",
        app_name=config.app.name,
        app_mode=config.app.mode,
        response_generator_type=config.response_generator.type,
    )
    runtime = create_runtime_coordinator(config)
    trace_logger.write("app:runtime_created")
    console_receiver = ConsoleInputReceiver()
    trace_logger.write("app:console_receiver_created")

    runtime_task = asyncio.create_task(runtime.run())
    trace_logger.write("app:runtime_task_started")

    await runtime.publish_event(
        AgentEvent(
            event_type=AgentEventType.APP_STARTED,
            payload={"source": "app_main"},
            priority=20,
            discardable=False,
        )
    )
    trace_logger.write("app:app_started_event_published")

    print("コンソール入力デモを開始します。終了するには exit または quit を入力してください。")
    trace_logger.write("app:console_receiver_starting")
    await console_receiver.start(runtime.publish_event)
    await console_receiver.wait_until_stopped()
    trace_logger.write("app:console_receiver_stopped")

    trace_logger.write("app:runtime_stop_requested")
    runtime.stop()
    await runtime_task
    trace_logger.write("app:runtime_task_finished")
    trace_logger.write("app:finished")
    print("終了しました。")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
