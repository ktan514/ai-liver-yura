from __future__ import annotations

from dataclasses import replace
from queue import Queue

import pytest

from app.adapters.llm import DummyResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.adapters.streaming import (
    FakeAvatarHealthAdapter,
    FakeObsPreparationAdapter,
    FakeObsPreparationConfig,
    FakeYouTubePreparationAdapter,
    FakeYouTubePreparationConfig,
    InMemoryCommentCandidateRepository,
    InMemoryCommentModerationRepository,
    InMemoryCommentRankingRepository,
    InMemoryCommentResponseActivityRepository,
    InMemoryCommentResponseHistory,
    InMemoryCommentResponseHistoryRepository,
    InMemoryCommentSelectionRepository,
    InMemoryStreamMainSegmentRepository,
    InMemoryStreamOpeningRepository,
    InMemoryStreamPreparationPublisher,
    InMemoryStreamSessionRepository,
    YamlRunOfShowRepository,
)
from app.adapters.streaming.fake_live_chat_adapter import FakeLiveChatAdapter
from app.adapters.streaming.fake_streaming_control import (
    FakeObsStreamingControlAdapter,
    FakeYouTubeStreamingControlAdapter,
)
from app.config.app_config import CommentRankingSettings, load_app_config
from app.domain.actions import ActionPlan
from app.domain.character import CharacterProfile
from app.domain.events import AgentEvent, AgentEventType
from app.domain.streaming import (
    ApproveNormalStreamEndCommand,
    ApproveStreamStartCommand,
    CommentRankingContext,
    HealthCheckItem,
    HealthStatus,
    StreamPreparationCommand,
    StreamSessionStatus,
    YouTubeBroadcastSummary,
)
from app.ports.youtube_live_chat import LiveChatMessageDto, LiveChatPageDto
from app.runtime import (
    ActionPlanner,
    ActivityManager,
    AgentLifeService,
    EventQueue,
    RuntimeCoordinator,
)
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
    ActivityPlanningService,
)
from app.runtime.planned_activity_queue import PlannedActivityQueue
from app.usecases import (
    CommentModerationUsecase,
    CommentRankingUsecase,
    CommentResponseUsecase,
    EndStreamSessionUsecase,
    PrepareStreamSessionUsecase,
    StartStreamSessionUsecase,
    StreamLifecycleGate,
    StreamMainSegmentUsecase,
    StreamOpeningUsecase,
    StreamPreparationRequirements,
    YouTubeLiveChatPoller,
)

ACTIVE = {
    "obs_output": "active",
    "youtube_stream": "active",
    "youtube_broadcast": "live",
    "stream_session": "live",
}


class RecordingActionExecutor:
    def __init__(self) -> None:
        self.actions: list[ActionPlan] = []

    async def execute(self, action_plan: ActionPlan) -> None:
        self.actions.append(action_plan)


class FakeTtsHealth:
    async def check(self, *, required: bool) -> HealthCheckItem:
        return HealthCheckItem("tts", "tts", HealthStatus.HEALTHY, required, "ready")


def build_runtime() -> tuple[RuntimeCoordinator, RecordingActionExecutor]:
    manager = ActivityManager()
    life = AgentLifeService(manager)
    requests: Queue[ActivityPlanningRequest] = Queue()
    planned = PlannedActivityQueue()
    generator = DummyResponseGenerator(
        CharacterProfile("Yura", "明るい", "自然", "配信", [], [], []),
        SimplePromptBuilder(),
    )
    planner = ActionPlanner(generator)
    executor = RecordingActionExecutor()
    scheduler = ActionScheduler(executor)
    planning = ActivityPlanningService(agent_life_service=life, activity_manager=manager)
    planner_thread = ActivityPlannerThread(requests, planned, planning)
    executor_thread = ActivityExecutorThread(planned, planner, scheduler, manager, life)
    return (
        RuntimeCoordinator(
            EventQueue(),
            manager,
            planner,
            scheduler,
            requests,
            planner_thread,
            executor_thread,
            agent_life_service=life,
        ),
        executor,
    )


def live_chat_page() -> LiveChatPageDto:
    return LiveChatPageDto(
        (
            LiveChatMessageDto(
                "message-1",
                "textMessageEvent",
                {
                    "type": "textMessageEvent",
                    "publishedAt": "2026-07-17T00:00:00Z",
                    "displayMessage": "ゲーム楽しいですか？",
                },
                {"channelId": "viewer-1", "displayName": "viewer"},
            ),
        ),
        None,
        1000,
    )


def assert_before(events: list[str], first: str, second: str) -> None:
    assert events.index(first) < events.index(second)


@pytest.mark.asyncio
async def test_streaming_vertical_happy_path_without_external_connections() -> None:
    config = load_app_config()
    broadcast_id = config.streaming.fake.broadcast_id
    youtube_preparation = FakeYouTubePreparationAdapter(
        FakeYouTubePreparationConfig(
            broadcasts=(YouTubeBroadcastSummary(broadcast_id, "vertical", live_chat_id="chat"),)
        )
    )
    sessions = InMemoryStreamSessionRepository()
    openings = InMemoryStreamOpeningRepository()
    mains = InMemoryStreamMainSegmentRepository()
    run_of_show = YamlRunOfShowRepository(config.streaming.run_of_show.directory)
    prepare = PrepareStreamSessionUsecase(
        youtube=youtube_preparation,
        obs=FakeObsPreparationAdapter(FakeObsPreparationConfig()),
        tts=FakeTtsHealth(),
        avatar=FakeAvatarHealthAdapter(HealthStatus.HEALTHY, "ready"),
        run_of_show=run_of_show,
        sessions=sessions,
        publisher=InMemoryStreamPreparationPublisher(),
        requirements=StreamPreparationRequirements(),
    )
    broadcast = (await prepare.list_broadcasts())[0]
    created = prepare.create_session(
        broadcast,
        trace_id="vertical-trace",
        run_of_show_id=config.streaming.run_of_show.default_id,
    )
    prepared = await prepare.execute(
        StreamPreparationCommand(
            "prepare-command",
            "vertical-trace",
            created.session_id,
            config.streaming.fake.broadcast_id,
            run_of_show_id=config.streaming.run_of_show.default_id,
        )
    )
    session = sessions.get(created.session_id)
    assert prepared.ready and prepared.session_id == created.session_id
    assert session is not None and session.status == StreamSessionStatus.READY
    assert session.live_chat_id and session.selected_stream_id

    obs = FakeObsStreamingControlAdapter(statuses=["idle", "active", "active", "active", "idle"])
    youtube = FakeYouTubeStreamingControlAdapter(
        stream_statuses=["active", "active", "inactive"],
        broadcast_statuses=["ready", "live", "live", "live", "complete"],
    )
    obs.adapter_type = "obs_websocket"
    youtube.adapter_type = "google"
    start = StartStreamSessionUsecase(
        sessions=sessions,
        obs=obs,
        youtube=youtube,
        poll_interval_seconds=0,
        step_timeout_seconds=1,
    )
    start_result = await start.execute(
        ApproveStreamStartCommand(
            "start-command",
            "vertical-trace",
            session.session_id,
            session.state_version,
            "operator",
        )
    )
    live = sessions.get(session.session_id)
    assert start_result.successful and live is not None
    assert live.status == StreamSessionStatus.LIVE
    assert obs.start_calls == youtube.transition_calls == 1

    coordinator, output = build_runtime()
    events: list[str] = ["stream_preparation.ready", "stream_start.live"]

    def publish(name: str, _data: dict[str, object], _trace: str) -> None:
        events.append(name)

    gate = StreamLifecycleGate(
        sessions=sessions,
        openings=openings,
        main_segments=mains,
        publisher=publish,
    )
    gate.update_external_state(session.session_id, ACTIVE)
    coordinator.configure_stream_lifecycle_gate(gate)
    main = StreamMainSegmentUsecase(
        sessions=sessions,
        activities=mains,
        run_of_show=run_of_show,
        executor=coordinator.execute_stream_main_segment,
        event_publisher=publish,
        lifecycle_gate=gate,
    )
    opening = StreamOpeningUsecase(
        sessions=sessions,
        openings=openings,
        run_of_show=run_of_show,
        executor=coordinator.execute_stream_opening,
        event_publisher=publish,
        lifecycle_gate=gate,
        completed_handler=main.start,
    )
    opening_activity = await opening.start(
        session.session_id,
        start_result,
        adapter_types=("google", "obs_websocket"),
    )
    main_activity = main.status(session.session_id)
    assert opening_activity.status.value == "completed"
    assert main_activity is not None and main_activity.status.value == "completed"
    speech_types = [item.action_type.value for item in output.actions]
    assert speech_types.count("speak") == 2
    assert "update_subtitle" in speech_types and "change_expression" in speech_types

    ranking_settings = replace(CommentRankingSettings(), selection_threshold=0.45)
    ranker = CommentRankingUsecase(
        gate=gate,
        candidates=InMemoryCommentCandidateRepository(20),
        rankings=InMemoryCommentRankingRepository(),
        selections=InMemoryCommentSelectionRepository(),
        history=InMemoryCommentResponseHistoryRepository(20),
        settings=ranking_settings,
        publisher=publish,
    )
    responder = CommentResponseUsecase(
        gate=gate,
        activities=InMemoryCommentResponseActivityRepository(),
        selections=ranker,
        history=InMemoryCommentResponseHistory(),
        executor=coordinator.execute_stream_comment_response,
        settings=config.streaming.comment_response,
        publisher=publish,
    )
    response_finished = __import__("asyncio").get_running_loop().create_future()

    def candidate_sink(candidate: object, trace_id: str) -> None:
        async def handle() -> None:
            target = await ranker.add_and_select(
                candidate,  # type: ignore[arg-type]
                CommentRankingContext(current_topic=str(main_activity.topic or "")),
                trace_id,
            )
            assert target is not None
            activity = await responder.start(target.session_id, target.selection_id, trace_id)
            response_finished.set_result(activity)

        __import__("asyncio").create_task(handle())

    moderation = CommentModerationUsecase(
        gate=gate,
        repository=InMemoryCommentModerationRepository(),
        settings=config.streaming.moderation,
        publisher=publish,
        candidate_sink=candidate_sink,
    )
    coordinator.configure_comment_moderation(moderation.evaluate_event)
    chat = FakeLiveChatAdapter(pages=[live_chat_page()])
    poller = YouTubeLiveChatPoller(
        session_id=session.session_id,
        trace_id="vertical-trace",
        broadcast_id=session.selected_broadcast_id,
        live_chat_id=str(session.live_chat_id),
        adapter=chat,
        gate=gate,
        event_sink=coordinator.publish_event,
        publisher=publish,
    )
    assert await poller.poll_once()
    response_activity = await response_finished
    assert response_activity.status.value == "completed"
    assert moderation.status(session.session_id).allowed == 1
    assert ranker.status(session.session_id).selected_count == 1
    assert ranker.current_selection(session.session_id) is None
    assert len(responder.recent(session.session_id)) == 1
    assert output.actions[-3].action_type.value in {
        "speak",
        "update_subtitle",
        "change_expression",
    }

    end = EndStreamSessionUsecase(
        sessions=sessions,
        main_segments=mains,
        run_of_show=run_of_show,
        obs=obs,
        youtube=youtube,
        closing_executor=coordinator.execute_stream_closing,
        output_canceler=coordinator.cancel_stream_outputs,
        event_publisher=publish,
        test_mode=True,
    )
    current = sessions.get(session.session_id)
    assert current is not None
    ended = await end.normal(
        ApproveNormalStreamEndCommand(
            "end-command", "vertical-trace", current.session_id, current.state_version, "operator"
        )
    )
    final = sessions.get(session.session_id)
    assert ended.successful and final is not None
    assert final.status == StreamSessionStatus.COMPLETED
    assert youtube.complete_calls == obs.stop_calls == 1
    assert (
        await end.normal(
            ApproveNormalStreamEndCommand(
                "end-command",
                "vertical-trace",
                current.session_id,
                current.state_version,
                "operator",
            )
        )
        == ended
    )

    assert_before(events, "stream_start.live", "stream_opening.started")
    assert_before(events, "stream_opening.completed", "stream_main_segment.started")
    assert_before(events, "stream_main_segment.completed", "stream_comments.ranking_started")
    assert_before(events, "stream_comments.target_selected", "stream_comments.response_started")
    assert_before(
        events, "stream_comments.response_speech_started", "stream_comments.reservation_consumed"
    )
    assert_before(events, "stream_closing.completed", "stream_end.broadcast_complete")
    assert_before(events, "stream_end.broadcast_complete", "stream_end.obs_idle")
    assert_before(events, "stream_end.obs_idle", "stream_end.completed")
    assert chat.calls == 1
    assert all("liveChatId" not in repr(event) for event in events)


@pytest.mark.asyncio
async def test_unconfigured_runtime_preserves_legacy_youtube_comment_route() -> None:
    coordinator, output = build_runtime()
    event = AgentEvent(
        AgentEventType.YOUTUBE_COMMENT,
        {"comment": "legacy comment", "message_id": "legacy"},
    )
    await coordinator.publish_event(event)
    await coordinator.run_once()
    assert any(item.action_type.value == "speak" for item in output.actions)
