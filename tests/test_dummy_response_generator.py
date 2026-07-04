

from __future__ import annotations

import pytest

from app.adapters.llm import DummyResponseGenerator
from app.domain.activities import Activity, ActivityType


@pytest.mark.asyncio
async def test_dummy_response_generator_generates_conversation_response() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={"event_payload": {"text": "こんにちは"}},
    )
    generator = DummyResponseGenerator()

    response = await generator.generate_response(activity)

    assert response == "ダミー応答: こんにちは"


@pytest.mark.asyncio
async def test_dummy_response_generator_generates_comment_response() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={"event_payload": {"comment": "コメントです"}},
    )
    generator = DummyResponseGenerator()

    response = await generator.generate_response(activity)

    assert response == "ダミー応答: コメントです"


@pytest.mark.asyncio
async def test_dummy_response_generator_generates_autonomous_talk_response() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話題を出して話す",
    )
    generator = DummyResponseGenerator()

    response = await generator.generate_response(activity)

    assert response == "ダミー自律発話: 何か面白い話題を考えています。"


@pytest.mark.asyncio
async def test_dummy_response_generator_generates_observation_response() -> None:
    activity = Activity(
        activity_type=ActivityType.IDLE_OBSERVATION,
        goal="状態を観察する",
    )
    generator = DummyResponseGenerator()

    response = await generator.generate_response(activity)

    assert response == "ダミー観察応答"