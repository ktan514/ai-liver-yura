from __future__ import annotations

import asyncio

from app.adapters.input import ConsoleInputReceiver
from app.adapters.llm import DummyResponseGenerator
from app.runtime import ActionPlanner, ActivityManager, EventQueue, RuntimeCoordinator
from app.usecases import ExecuteActionUsecase


async def async_main() -> None:
    event_queue = EventQueue()
    activity_manager = ActivityManager()
    response_generator = DummyResponseGenerator()
    action_planner = ActionPlanner(response_generator=response_generator)
    action_executor = ExecuteActionUsecase()

    runtime = RuntimeCoordinator(
        event_queue=event_queue,
        activity_manager=activity_manager,
        action_planner=action_planner,
        action_executor=action_executor,
    )
    console_receiver = ConsoleInputReceiver()

    runtime_task = asyncio.create_task(runtime.run())

    print("コンソール入力デモを開始します。終了するには exit または quit を入力してください。")
    await console_receiver.start(runtime.publish_event)
    await console_receiver.wait_until_stopped()

    runtime.stop()
    await runtime_task
    print("終了しました。")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
