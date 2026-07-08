from __future__ import annotations

from app.adapters.prompt import SimplePromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.runtime.short_term_memory import ShortTermMemory


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
    assert "# 会話応答方針" in prompt
    assert "- これはユーザー入力への応答である" in prompt
    assert "- ユーザーの話題を受け止めつつ、AIライバーのキャラクターとして短く返答する" in prompt


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
    assert "# 自律発話方針" in prompt
    assert "- 直近発話を丸ごと続けるのではなく、配信トークの流れとして自然につなげる" in prompt
    assert "- いきなり豆知識や新しい話題の本題から始めない" in prompt
    assert "- 直近発話ですでに準備状態、眠気、目が覚める感覚に触れている場合、それらの状態描写を繰り返さない" in prompt
    assert "# 自律発話の組み立て手順" in prompt
    assert "- 1文目: 直近発話、現在の状態、または今の気分を短く受ける" in prompt
    assert "- 2文目: 自分が話したい話題を少し広げる" in prompt
    assert "- 直近発話と同じ主題、同じ情景、同じ願望を続けて繰り返さない" in prompt
    assert "# 自律発話で避けること" in prompt
    assert "- 例文をそのままコピーする" in prompt
    assert "- 準備中、起動直後、眠気、目が覚める、声の調子などの状態表現を何度も繰り返す" in prompt
    assert "- 直近発話と同じ話題を、言い換えただけで続ける" in prompt
    assert "- 直近発話と同じ願望や余韻で締める" in prompt
    assert "現在の活動目的と直近文脈に沿って、キャラクターとして自然な配信トークを1〜3文で発話してください。" in prompt


def test_simple_prompt_builder_includes_recent_speech_connection_examples() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話題を出して話す",
    )
    character_profile = _create_character_profile()
    short_term_memory = ShortTermMemory()
    short_term_memory.add_speech(
        text="よし、起動できたみたい。声の調子も少しずつ整えていくね。",
        activity_type="startup_reaction",
    )
    prompt_builder = SimplePromptBuilder(short_term_memory=short_term_memory)

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "# 直近発話の扱い" in prompt
    assert "- このセクションでは、直近発話を受けた自然なトーク接続だけを設計する" in prompt
    assert "- 起動直後の準備状態、眠気、目が覚める感覚に触れるのは最初の1回までにする" in prompt
    assert "- 直近発話で準備状態や眠気に触れている場合、次の発話ではその状態描写を繰り返さない" in prompt
    assert "- 直近発話と同じ主題、同じ情景、同じ願望を続けて繰り返さない" in prompt
    assert "- 直近発話で使った印象的な語句をそのまま再利用しない" in prompt
    assert "- 直近発話と同じ願望や締め方で終わらせない" in prompt
    assert "- 直近発話と似た話を続ける場合は、対象・視点・感情のどれかを明確に変える" in prompt
    assert "# トーク接続例" in prompt
    assert "- 例文の固有表現、言い回し、語尾をそのままコピーしない" in prompt
    assert "例1: 起動直後から最初の雑談へ移る場合" in prompt
    assert "例2: 同じ話題を少し広げる場合" in prompt
    assert "例3: 関連する別の話題へ移る場合" in prompt
    assert "例4: 話題を変える場合" in prompt


def test_simple_prompt_builder_includes_startup_reaction_instruction() -> None:
    activity = Activity(
        activity_type=ActivityType.STARTUP_REACTION,
        goal="起動直後の状況に反応する",
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "活動種別: startup_reaction" in prompt
    assert "目的: 起動直後の状況に反応する" in prompt
    assert "# ライフサイクル発話方針" in prompt
    assert "# 起動直後の発話方針" in prompt
    assert "- 起動したこと、準備を始めること、少し目が覚めたような反応を自然に言う" in prompt
    assert "- おはよう、こんにちは、こんばんはなど、現在時刻に依存する挨拶を使わない" in prompt
    assert "- 豆知識や自由な雑談を始めない" in prompt


def test_simple_prompt_builder_includes_stream_opening_greeting_instruction() -> None:
    activity = Activity(
        activity_type=ActivityType.STREAM_OPENING_GREETING,
        goal="配信開始時のあいさつをする",
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "活動種別: stream_opening_greeting" in prompt
    assert "目的: 配信開始時のあいさつをする" in prompt
    assert "# ライフサイクル発話方針" in prompt
    assert "# 配信開始時の発話方針" in prompt
    assert "- 配信開始のあいさつをする" in prompt
    assert "- これから話していく雰囲気を作る" in prompt


def test_simple_prompt_builder_includes_stream_closing_greeting_instruction() -> None:
    activity = Activity(
        activity_type=ActivityType.STREAM_CLOSING_GREETING,
        goal="配信終了前のあいさつをする",
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "活動種別: stream_closing_greeting" in prompt
    assert "目的: 配信終了前のあいさつをする" in prompt
    assert "# ライフサイクル発話方針" in prompt
    assert "# 配信終了前の発話方針" in prompt
    assert "- 配信を締めるあいさつをする" in prompt
    assert "- 新しい話題を始めない" in prompt


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