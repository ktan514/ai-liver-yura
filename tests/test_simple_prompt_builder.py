from __future__ import annotations

from app.adapters.prompt import SimplePromptBuilder
from app.domain.activities import Activity, ActivityResult, ActivityType, OngoingActivity
from app.domain.character import CharacterProfile
from app.domain.games import GameInputClassification, GameInputClassificationResult
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicCategory, TopicHistory
from app.domain.topic_memory import SimilarTopicMemory, TopicMemoryEntry


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


def _create_topic_memory_entry(
    category: TopicCategory,
    summary: str,
) -> TopicMemoryEntry:
    return TopicMemoryEntry(
        category=category,
        summary=summary,
        source_text=summary,
        activity_type="speak",
        embedding=[0.1, 0.2, 0.3],
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


def test_simple_prompt_builder_includes_ongoing_activity_state() -> None:
    ongoing = OngoingActivity(
        activity_type="shiritori",
        goal="ユーザーとしりとりを続ける",
        expected_input="『ぱ』から始まる単語",
        end_condition="終了希望または『ん』で終わる単語",
        last_result=ActivityResult(
            result_type="speech_output",
            summary="らっぱ！ 次は『ぱ』だよ。",
        ),
        context={"last_word": "らっぱ"},
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="複数ターン活動「shiritori」を継続する",
        context={
            "event_payload": {"text": "ぱんだ"},
            "ongoing_activity": ongoing,
            "ongoing_activity_id": ongoing.ongoing_activity_id,
            "is_ongoing_activity_input": True,
        },
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "# 継続中の複数ターン活動" in prompt
    assert "活動種別: shiritori" in prompt
    assert "状態: active" in prompt
    assert "開始時の目的: ユーザーとしりとりを続ける" in prompt
    assert "直前のActivity結果種別: speech_output" in prompt
    assert "直前のActivity結果: らっぱ！ 次は『ぱ』だよ。" in prompt
    assert "次に期待する入力: 『ぱ』から始まる単語" in prompt
    assert "終了条件: 終了希望または『ん』で終わる単語" in prompt
    assert "今回の入力は通常会話ではなく、この活動を継続する入力として扱う" in prompt
    assert "# 会話応答方針" in prompt
    assert "- これはユーザー入力への応答である" in prompt
    assert "- ユーザーの話題を受け止めつつ、AIライバーのキャラクターとして短く返答する" in prompt


def test_autonomous_prompt_includes_topic_continuation_decision() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="中断後の話題進路に沿って話す",
        context={
            "event_payload": {
                "continuation_decision": "resume_with_reframing",
                "continuation_reasons": ["resume_score_high"],
                "interrupted_topic": "将来の配信でやりたいこと",
                "selected_topic": "将来の配信でやりたいこと",
                "reintroduction_required": True,
            }
        },
    )

    prompt = SimplePromptBuilder().build_prompt(activity, _create_character_profile())

    assert "# 中断後の話題進路" in prompt
    assert "判断: resume_with_reframing" in prompt
    assert "中断前の話題: 将来の配信でやりたいこと" in prompt
    assert "再導入が必要: はい" in prompt
    assert "同じ内容を繰り返さず続きを話す" in prompt


def test_game_activity_prompt_includes_generic_session_context() -> None:
    activity = Activity(
        activity_type=ActivityType.GAME_WITH_USER,
        goal="テストゲームを進行する",
        context={
            "game_session_id": "session-1",
            "game_type": "fake_game",
            "game_status": "playing",
            "game_current_turn": 2,
            "game_metadata": {"board": []},
        },
    )

    prompt = SimplePromptBuilder().build_prompt(activity, _create_character_profile())

    assert "# GameSession" in prompt
    assert "session_id: session-1" in prompt
    assert "game_type: fake_game" in prompt
    assert "status: playing" in prompt
    assert "current_turn: 2" in prompt


def test_shiritori_ai_turn_prompt_requires_structured_output() -> None:
    activity = Activity(
        activity_type=ActivityType.GAME_WITH_USER,
        goal="しりとりのAIターン",
        context={
            "game_session_id": "session-1",
            "game_type": "shiritori",
            "game_status": "playing",
            "game_current_turn": 1,
            "game_metadata": {},
            "shiritori_action": "generate_ai_word",
            "current_turn": "ai",
            "last_word": "うみ",
            "expected_head": "み",
            "used_words": ["うみ"],
            "turn_count": 1,
        },
    )

    prompt = SimplePromptBuilder().build_prompt(activity, _create_character_profile())

    assert "# しりとり共通ルール" in prompt
    assert "必要な開始文字: み" in prompt
    assert '"game_action":"play_word"' in prompt
    assert "wordには判定対象の単語だけ" in prompt
    assert "名前: ミナト" in prompt


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
    assert (
        "- 直近発話ですでに準備状態、眠気、目が覚める感覚に触れている場合、"
        "それらの状態描写を繰り返さない"
        in prompt
    )
    assert "# 自律発話の組み立て手順" in prompt
    assert "- 1文目: 直近発話、現在の状態、または今の気分を短く受ける" in prompt
    assert "- 2文目: 自分が話したい話題を少し広げる" in prompt
    assert "- 直近発話と同じ主題、同じ情景、同じ願望を続けて繰り返さない" in prompt
    assert "# 自律発話で避けること" in prompt
    assert "- 例文をそのままコピーする" in prompt
    assert "- 準備中、起動直後、眠気、目が覚める、声の調子などの状態表現を何度も繰り返す" in prompt
    assert "- 直近発話と同じ話題を、言い換えただけで続ける" in prompt
    assert "- 直近発話と同じ願望や余韻で締める" in prompt
    assert (
        "現在の活動目的と直近文脈に沿って、キャラクターとして自然な配信トークを1〜3文で発話してください。"
        in prompt
    )


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
    assert (
        "- 直近発話で準備状態や眠気に触れている場合、次の発話ではその状態描写を繰り返さない"
        in prompt
    )
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


def test_simple_prompt_builder_includes_topic_history_for_autonomous_talk() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話題を出して話す",
    )
    character_profile = _create_character_profile()
    topic_history = TopicHistory()
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海の光")
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="潮の流れ")
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="岩場の生き物")
    prompt_builder = SimplePromptBuilder(topic_history=topic_history)

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "# 直近の話題履歴" in prompt
    assert "- sea_life: 海の光" in prompt
    assert "- sea_life: 潮の流れ" in prompt
    assert "- sea_life: 岩場の生き物" in prompt
    assert "# 話題選択の注意" in prompt
    assert "- 直近で sea_life 系の話題が続いているため、次は別カテゴリへ自然に広げる" in prompt
    assert "- 話題を変える場合は、直前の話題との共通点を使って自然に橋渡しする" in prompt
    assert "- 同じ大テーマの細部だけを掘り続けない" in prompt


def test_simple_prompt_builder_includes_related_topic_memories_for_autonomous_talk() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話題を出して話す",
        context={
            "similar_topic_memories": [
                SimilarTopicMemory(
                    entry=_create_topic_memory_entry(
                        category=TopicCategory.NATURE,
                        summary="海辺の静かな雰囲気について話した記憶",
                    ),
                    similarity=0.82,
                ),
                SimilarTopicMemory(
                    entry=_create_topic_memory_entry(
                        category=TopicCategory.SEA_LIFE,
                        summary="クラゲ展示がきれいだった記憶",
                    ),
                    similarity=0.91,
                ),
            ]
        },
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "# 関連する過去の記憶" in prompt
    assert "- sea_life: クラゲ展示がきれいだった記憶" in prompt
    assert "- nature: 海辺の静かな雰囲気について話した記憶" in prompt
    assert prompt.index("- sea_life: クラゲ展示がきれいだった記憶") < prompt.index(
        "- nature: 海辺の静かな雰囲気について話した記憶"
    )
    assert "# 関連記憶の扱い" in prompt
    assert "- 関連記憶をそのまま読み上げず、必要な要素だけを会話の流れに溶け込ませる" in prompt
    assert "- 関連性が低い場合は無理に使わない" in prompt


def test_simple_prompt_builder_does_not_include_related_topic_memories_for_conversation() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={
            "event_payload": {"text": "こんにちは"},
            "similar_topic_memories": [
                SimilarTopicMemory(
                    entry=_create_topic_memory_entry(
                        category=TopicCategory.SEA_LIFE,
                        summary="クラゲ展示がきれいだった記憶",
                    ),
                    similarity=0.91,
                )
            ],
        },
    )
    character_profile = _create_character_profile()
    prompt_builder = SimplePromptBuilder()

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "# 関連する過去の記憶" not in prompt
    assert "# 関連記憶の扱い" not in prompt
    assert "クラゲ展示がきれいだった記憶" not in prompt


def test_simple_prompt_builder_does_not_include_topic_history_for_conversation() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={"event_payload": {"text": "こんにちは"}},
    )
    character_profile = _create_character_profile()
    topic_history = TopicHistory()
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海の光")
    prompt_builder = SimplePromptBuilder(topic_history=topic_history)

    prompt = prompt_builder.build_prompt(activity, character_profile)

    assert "# 直近の話題履歴" not in prompt
    assert "# 話題選択の注意" not in prompt


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


def test_simple_prompt_builder_builds_static_game_input_classification_prompt() -> None:
    activity = Activity(
        activity_type=ActivityType.GAME_INPUT_CLASSIFICATION,
        goal="入力を分類する",
        context={
            "user_text": "どうかな",
            "game_type": "shiritori",
            "game_status": "playing",
            "current_turn": "user",
            "last_word": "はさみ",
            "expected_head": "み",
            "supported_games": ["shiritori"],
        },
    )

    prompt = SimplePromptBuilder().build_prompt(activity, _create_character_profile())

    assert "応答文を作らず、指定されたJSONのみ返してください" in prompt
    assert "- mixed: ゲームの手と雑談の両方を含む" in prompt
    assert "ユーザー入力: どうかな" in prompt
    assert "# キャラクター設定" not in prompt


def test_conversation_prompt_includes_classified_game_context() -> None:
    result = GameInputClassificationResult(
        classification=GameInputClassification.AMBIGUOUS,
        confidence=0.5,
        raw_text="それでいいよ",
        classifier_type="deterministic",
        game_type="shiritori",
        reason="ambiguous_short_phrase",
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={
            "event_payload": {
                "text": "それでいいよ",
                "game_input_classification": result,
                "game_session_context": {
                    "game_type": "shiritori",
                    "game_status": "playing",
                    "current_turn": "user",
                    "last_word": "はさみ",
                    "expected_head": "み",
                },
                "confirmation_required": True,
            }
        },
    )

    prompt = SimplePromptBuilder().build_prompt(activity, _create_character_profile())

    assert "# ゲーム入力の分類結果" in prompt
    assert "分類: ambiguous" in prompt
    assert "確認が必要: True" in prompt
    assert "次に必要な文字: み" in prompt


def test_conversation_prompt_prevents_unverified_execution_generically() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
        context={
            "event_payload": {
                "text": "何かゲームしよう",
                "available_plugin_capabilities": [],
                "execution_request_unmatched": True,
                "execution_performed": False,
                "available_alternative": "文字での通常会話",
            }
        },
    )

    prompt = SimplePromptBuilder().build_prompt(activity, _create_character_profile())

    assert "開始・取得・操作・登録・確認・視認・聴取したように表現してはいけない" in prompt
    assert "Plugin、Capability、Providerなど内部構成を示す語を返答に出してはいけない" in prompt
    assert "話題についての知識説明や感想まで拒否してはいけない" in prompt
    assert "現在可能な代替: 文字での通常会話" in prompt
