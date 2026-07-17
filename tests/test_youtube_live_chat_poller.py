from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.adapters.streaming import (
    FakeLiveChatAdapter,
    InMemoryStreamMainSegmentRepository,
    InMemoryStreamOpeningRepository,
)
from app.adapters.streaming.in_memory_session_repository import InMemoryStreamSessionRepository
from app.adapters.youtube.google_youtube_live_chat_adapter import GoogleYouTubeLiveChatAdapter
from app.adapters.youtube.youtube_api_error_mapper import YouTubeApiError, YouTubeApiErrorKind
from app.domain.events import AgentEvent
from app.domain.streaming import StreamSession, StreamSessionStatus
from app.ports.youtube_live_chat import LiveChatMessageDto, LiveChatPageDto
from app.usecases import StreamLifecycleGate, YouTubeLiveChatPoller

ACTIVE = {
    "obs_output": "active",
    "youtube_stream": "active",
    "youtube_broadcast": "live",
    "stream_session": "live",
}


def message(
    message_id: str,
    kind: str = "textMessageEvent",
    *,
    published: str = "2026-01-01T00:00:00Z",
    owner: bool = False,
) -> LiveChatMessageDto:
    snippet: dict[str, object] = {
        "type": kind,
        "publishedAt": published,
        "displayMessage": f"message-{message_id}",
    }
    if kind == "superChatEvent":
        snippet["superChatDetails"] = {
            "amountDisplayString": "¥1,000",
            "currency": "JPY",
        }
    return LiveChatMessageDto(
        message_id,
        kind,
        snippet,
        {
            "channelId": f"channel-{message_id}",
            "displayName": "viewer",
            "isChatOwner": owner,
        },
    )


def setup(
    pages: list[LiveChatPageDto], **options: object
) -> tuple[
    YouTubeLiveChatPoller,
    list[AgentEvent],
    list[str],
    InMemoryStreamSessionRepository,
    StreamSession,
]:
    sessions = InMemoryStreamSessionRepository()
    session = sessions.create(
        StreamSession(
            "trace",
            "broadcast",
            "title",
            status=StreamSessionStatus.LIVE,
            live_chat_id="secret-chat-id",
        )
    )
    gate = StreamLifecycleGate(
        sessions=sessions,
        openings=InMemoryStreamOpeningRepository(),
        main_segments=InMemoryStreamMainSegmentRepository(),
    )
    gate.update_external_state(session.session_id, ACTIVE)
    events: list[AgentEvent] = []
    notifications: list[str] = []

    async def sink(event: AgentEvent) -> None:
        events.append(event)

    poller = YouTubeLiveChatPoller(
        session_id=session.session_id,
        trace_id="trace",
        broadcast_id="broadcast",
        live_chat_id="secret-chat-id",
        adapter=FakeLiveChatAdapter(pages=list(pages)),
        gate=gate,
        event_sink=sink,
        publisher=lambda event, _data, _trace: notifications.append(event),
        **options,  # type: ignore[arg-type]
    )
    return poller, events, notifications, sessions, session


@pytest.mark.asyncio
async def test_poll_normalizes_orders_and_deduplicates_across_pages() -> None:
    poller, events, notifications, _sessions, session = setup(
        [
            LiveChatPageDto(
                (message("2", published="2026-01-01T00:00:02Z"), message("1")),
                "next",
                1500,
            ),
            LiveChatPageDto((message("2"), message("3", "superChatEvent")), None, 2500),
        ]
    )
    assert await poller.poll_once()
    assert [event.payload["message_id"] for event in events] == ["1", "2"]
    assert await poller.poll_once()
    assert [event.payload["message_id"] for event in events] == ["1", "2", "3"]
    assert poller.status.received_count == 4
    assert poller.status.emitted_count == 3
    assert poller.status.duplicate_count == 1
    assert poller.status.current_interval_ms == 2500
    assert events[-1].priority == 80
    assert events[-1].payload["session_id"] == session.session_id
    assert "stream_comments.message_received" in notifications
    assert "stream_comments.message_deduplicated" in notifications


@pytest.mark.asyncio
async def test_lifecycle_change_discards_pending_result_and_stops() -> None:
    poller, events, notifications, sessions, session = setup(
        [LiveChatPageDto((message("1"),), None, 1000)]
    )
    closing = sessions.save(session.transition(StreamSessionStatus.CLOSING_REQUESTED))
    assert not await poller.poll_once()
    assert not events
    assert poller.status.status == "stopped"
    assert poller.status.lifecycle_stop_reason == "lifecycle.ending"
    assert "stream_comments.polling_stopped" in notifications
    assert closing.status == StreamSessionStatus.CLOSING_REQUESTED


@pytest.mark.asyncio
async def test_backpressure_preserves_paid_and_owner_and_counts_drop() -> None:
    page = LiveChatPageDto(
        (
            message("viewer-1"),
            message("viewer-2"),
            message("paid", "superChatEvent"),
            message("owner", owner=True),
        ),
        None,
        1000,
    )
    poller, events, notifications, _sessions, _session = setup(
        [page], max_messages_per_poll=2, max_events_per_second=2
    )
    assert await poller.poll_once()
    assert {event.payload["message_id"] for event in events} == {"paid", "owner"}
    assert poller.status.dropped_count == 2
    assert "stream_comments.message_dropped" in notifications


@pytest.mark.asyncio
async def test_deleted_and_unknown_are_not_converted_to_text_type() -> None:
    poller, events, _notifications, _sessions, _session = setup(
        [
            LiveChatPageDto(
                (message("deleted", "messageDeletedEvent"), message("x", "futureKind")),
                None,
                1000,
            )
        ]
    )
    assert await poller.poll_once()
    assert [event.payload["message_type"] for event in events] == ["deleted", "unknown"]


@pytest.mark.asyncio
async def test_transient_backoff_and_auth_failure() -> None:
    transient, _events, notifications, _sessions, _session = setup([])
    transient._adapter = FakeLiveChatAdapter(  # type: ignore[attr-defined]
        error=YouTubeApiError(YouTubeApiErrorKind.NETWORK, "network", retryable=True)
    )
    assert await transient.poll_once()
    assert transient.status.status == "backing_off"
    assert transient.status.current_interval_ms >= 1000
    assert "stream_comments.polling_backoff" in notifications

    auth, _events, notifications, _sessions, _session = setup([])
    auth._adapter = FakeLiveChatAdapter(  # type: ignore[attr-defined]
        error=YouTubeApiError(YouTubeApiErrorKind.AUTHENTICATION, "auth")
    )
    assert not await auth.poll_once()
    assert auth.status.failure_code == "live_chat.auth_failed"
    assert "stream_comments.polling_failed" in notifications


class Request:
    def __init__(self, value: object) -> None:
        self.value = value

    def execute(self, num_retries: int) -> object:
        assert num_retries == 0
        return self.value


class Client:
    def __init__(self, value: object) -> None:
        self.value = value

    def liveChatMessages(self) -> Client:  # noqa: N802
        return self

    def list(self, **kwargs: object) -> Request:
        assert kwargs["part"] == "id,snippet,authorDetails"
        return Request(self.value)


class Factory:
    def __init__(self, value: object) -> None:
        self.value = value

    def create(self) -> Client:
        return Client(self.value)


@pytest.mark.asyncio
async def test_google_adapter_parses_page_without_leaking_raw_response() -> None:
    adapter = GoogleYouTubeLiveChatAdapter(
        Factory(
            {
                "items": [
                    {
                        "id": "m1",
                        "snippet": {
                            "type": "textMessageEvent",
                            "publishedAt": datetime.now(timezone.utc).isoformat(),
                        },
                        "authorDetails": {"displayName": "name"},
                    }
                ],
                "nextPageToken": "next",
                "pollingIntervalMillis": 3000,
                "secret": "must-not-cross-boundary",
            }
        )
    )
    page = await adapter.list_messages("chat", None, 100)
    assert page.next_page_token == "next"
    assert page.polling_interval_ms == 3000
    assert page.messages[0].message_id == "m1"
    assert not hasattr(page, "secret")


@pytest.mark.asyncio
async def test_google_adapter_rejects_malformed_response() -> None:
    adapter = GoogleYouTubeLiveChatAdapter(Factory({"items": []}))
    with pytest.raises(YouTubeApiError) as captured:
        await adapter.list_messages("chat", None, 100)
    assert captured.value.kind == YouTubeApiErrorKind.INVALID_RESPONSE
