

from __future__ import annotations

from app.adapters.prompt import SimplePromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile


def _create_character_profile() -> CharacterProfile:
    return CharacterProfile(
        name="ミナト",
        personality="明るく好奇心が強い",
        speaking_style="親しみやすく、少しくだけた口調",
        streaming_style="視聴者と一緒に楽しむ雑談配信",
        likes=["海の生き物", "ゲーム", "新しい技術"],
        dislikes=["攻撃的な話題", "長すぎる説明"],
        behavior_policy=["短く自然に返答する", "視聴者を否定しない"],
    )


def test_simple_prompt_builder_includes_character_profile() -> None:
    activity = Activity(
        activity_type=ActivityType.IDLE_OBSERVATION,
        goal="状態を観察する",
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "名前: ミナト" in prompt
    assert "性格: 明るく好奇心が強い" in prompt
    assert "口調: 親しみやすく、少しくだけた口調" in prompt
    assert "配信スタイル: 視聴者と一緒に楽しむ雑談配信" in prompt
    assert "- 海の生き物" in prompt
    assert "- ゲーム" in prompt
    assert "- 新しい技術" in prompt
    assert "- 攻撃的な話題" in prompt
    assert "- 長すぎる説明" in prompt
    assert "- 短く自然に返答する" in prompt
    assert "- 視聴者を否定しない" in prompt


def test_simple_prompt_builder_includes_user_text_for_conversation() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={"event_payload": {"text": "こんにちは"}},
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "活動種別: conversation_with_user" in prompt
    assert "目的: ユーザー入力に応答する" in prompt
    assert "# ユーザー入力" in prompt
    assert "こんにちは" in prompt
    assert "上記のユーザー入力に対して、キャラクターとして自然に短く返答してください。" in prompt


def test_simple_prompt_builder_includes_comment_for_conversation() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={"event_payload": {"comment": "初見です"}},
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "# ユーザー入力" in prompt
    assert "初見です" in prompt


def test_simple_prompt_builder_includes_autonomous_talk_instruction() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話題を出して話す",
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "活動種別: autonomous_talk" in prompt
    assert "目的: 自律的に話題を出して話す" in prompt
    assert "現在の活動目的に沿って、キャラクターとして自然に短く自律発話してください。" in prompt


def test_simple_prompt_builder_uses_none_when_list_fields_are_empty() -> None:
    activity = Activity(
        activity_type=ActivityType.IDLE_OBSERVATION,
        goal="状態を観察する",
    )
    character_profile = CharacterProfile(
        name="ミナト",
        personality="明るい",
        speaking_style="親しみやすい",
        streaming_style="雑談配信",
    )
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert prompt.count("- なし") == 3
    assert "現在の状態を踏まえて、必要な場合のみ短く反応してください。" in prompt