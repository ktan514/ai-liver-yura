from __future__ import annotations

import pytest

from app.adapters.llm import DummyResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile


def _create_character_profile() -> CharacterProfile:
    return CharacterProfile(
        name="ミナト",
        personality="明るく好奇心が強い",
        speaking_style="親しみやすく、少しくだけた口調",
        streaming_style="視聴者と一緒に楽しむ雑談配信",
        likes=["海の生き物", "ゲーム"],
        dislikes=["攻撃的な話題"],
        behavior_policy=["短く自然に返答する"],
    )


def _create_generator() -> DummyResponseGenerator:
    return DummyResponseGenerator(
        character_profile=_create_character_profile(),
        prompt_builder=SimplePromptBuilder(),
    )


@pytest.mark.asyncio
async def test_dummy_response_generator_generates_conversation_response() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={"event_payload": {"text": "こんにちは"}},
    )
    generator = _create_generator()

    response = await generator.generate_response(activity)

    assert response == "ダミー応答: こんにちは"
    assert generator.latest_prompt is not None
    assert "名前: ミナト" in generator.latest_prompt
    assert "こんにちは" in generator.latest_prompt


@pytest.mark.asyncio
async def test_dummy_response_generator_generates_comment_response() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={"event_payload": {"comment": "コメントです"}},
    )
    generator = _create_generator()

    response = await generator.generate_response(activity)

    assert response == "ダミー応答: コメントです"
    assert generator.latest_prompt is not None
    assert "コメントです" in generator.latest_prompt


@pytest.mark.asyncio
async def test_dummy_response_generator_generates_autonomous_talk_response() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話題を出して話す",
    )
    generator = _create_generator()

    response = await generator.generate_response(activity)

    assert response == "ダミー自律発話: 何か面白い話題を考えています。"
    assert generator.latest_prompt is not None
    assert "活動種別: autonomous_talk" in generator.latest_prompt
    assert "自律的に話題を出して話す" in generator.latest_prompt


@pytest.mark.asyncio
async def test_dummy_response_generator_generates_observation_response() -> None:
    activity = Activity(
        activity_type=ActivityType.IDLE_OBSERVATION,
        goal="状態を観察する",
    )
    generator = _create_generator()

    response = await generator.generate_response(activity)

    assert response == "ダミー観察応答"
    assert generator.latest_prompt is not None
    assert "活動種別: idle_observation" in generator.latest_prompt
    assert "状態を観察する" in generator.latest_prompt
