from app.domain.character_response import ActivityExecutionResult, ActivityExecutionStatus
from app.runtime.activity_manager import ActivityManager
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator


def test_generic_ongoing_activity_records_turns_and_completes() -> None:
    manager = ActivityManager()
    coordinator = OngoingActivityCoordinator(manager)

    started = coordinator.start(
        activity_type="dummy_multi_turn",
        goal="複数ターンの作業を完了する",
        expected_input="次の入力",
        end_condition="ユーザーが完了を選ぶ",
        context={"plugin_id": "dummy", "constraints": {"mode": "test"}},
        input_text="開始",
        source_event_id="event-1",
        operation="start",
        constraints={"mode": "test"},
    )
    waiting_result = ActivityExecutionResult(
        activity_type="dummy_multi_turn",
        operation="start",
        status=ActivityExecutionStatus.WAITING_INPUT,
        payload={"summary": "入力待ち"},
        constraints={"mode": "test"},
    )
    waiting = coordinator.record_execution(
        waiting_result,
        context_updates={"step": 1},
        expected_input="続きの入力",
        waiting_input=True,
    )

    assert waiting.ongoing_activity_id == started.ongoing_activity_id
    assert waiting.status.value == "waiting"
    assert waiting.turns[0].execution_result == waiting_result

    continued = coordinator.begin_turn(
        input_text="続ける",
        source_event_id="event-2",
        operation="continue",
        constraints={"mode": "test"},
    )
    continued_result = ActivityExecutionResult(
        activity_type="dummy_multi_turn",
        operation="continue",
        status=ActivityExecutionStatus.SUCCEEDED,
        payload={"summary": "完了"},
        constraints={"mode": "test"},
    )
    coordinator.record_execution(
        continued_result,
        context_updates={"step": 2},
        expected_input="",
        waiting_input=False,
    )
    completed = coordinator.complete(reason="dummy_completed")

    assert completed is not None
    assert completed.ongoing_activity_id == continued.ongoing_activity_id
    assert completed.status.value == "completed"
    assert len(completed.turns) == 2
    assert manager.ongoing_activity is None
    assert manager.ongoing_activity_history[-1] == completed
