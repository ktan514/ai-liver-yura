import asyncio
import json
from typing import Any
from urllib.request import Request

import pytest

from app.adapters.input.web_input_receiver import (
    WebInputReceiverConfig,
    _WebInputProtocol,
)
from app.adapters.web_conversation import (
    WebConversationClient,
    WebConversationClientConfig,
)
from app.domain.events import AgentEvent, InputAuthority


@pytest.mark.asyncio
async def test_web_input_protocol_accepts_only_valid_user_text() -> None:
    events: list[AgentEvent] = []
    tasks: set[asyncio.Task[None]] = set()

    async def publish(event: AgentEvent) -> None:
        events.append(event)

    def finished(task: asyncio.Task[None]) -> None:
        tasks.discard(task)
        task.result()

    protocol = _WebInputProtocol(
        publish,
        WebInputReceiverConfig(),
        tasks.add,
        finished,
    )
    protocol.datagram_received(b"not-json", ("127.0.0.1", 1))
    protocol.datagram_received(
        json.dumps(
            {"schema_version": 1, "type": "user_text", "text": "  こんにちは  "},
            ensure_ascii=False,
        ).encode(),
        ("127.0.0.1", 1),
    )
    await asyncio.gather(*tuple(tasks))

    assert len(events) == 1
    assert events[0].payload == {"text": "こんにちは", "source": "web"}
    assert events[0].authority == InputAuthority.USER


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_web_conversation_client_publishes_text_and_waits_for_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Request] = []

    def fake_urlopen(request: Request, timeout: float) -> _Response:
        del timeout
        requests.append(request)
        return _Response(b'{"status":"completed"}')

    monkeypatch.setattr(
        "app.adapters.web_conversation.client.urlopen",
        fake_urlopen,
    )
    client = WebConversationClient(
        WebConversationClientConfig(base_url="http://127.0.0.1:18770")
    )

    await client.publish_text(kind="speak", text="こんにちは", action_id="action-1")
    await client.play(b"RIFF-test-wav")

    assert [request.full_url for request in requests] == [
        "http://127.0.0.1:18770/api/output",
        "http://127.0.0.1:18770/api/audio",
    ]
    text_payload: dict[str, Any] = json.loads(bytes(requests[0].data or b""))
    assert text_payload["text"] == "こんにちは"
    assert requests[1].data == b"RIFF-test-wav"
