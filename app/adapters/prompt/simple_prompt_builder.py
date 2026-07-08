from __future__ import annotations

from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.runtime import PromptBuilder
from app.runtime.short_term_memory import ShortTermMemory


class CharacterPromptSections:
    """CharacterProfile から共通 prompt section を組み立てる。"""

    def build(self, character_profile: CharacterProfile) -> list[str]:
        return [
            "あなたは以下のAIライバーです。",
            "",
            "# キャラクター設定",
            f"名前: {character_profile.name}",
            f"性格: {character_profile.personality}",
            f"口調: {character_profile.speaking_style}",
            f"配信スタイル: {character_profile.streaming_style}",
            "",
            "# 好きな話題・もの",
            *self._format_items(character_profile.likes),
            "",
            "# 苦手な話題・もの",
            *self._format_items(character_profile.dislikes),
            "",
            "# 行動方針・禁止事項",
            *self._format_items(character_profile.behavior_policy),
        ]

    def _format_items(self, items: list[str]) -> list[str]:
        if not items:
            return ["- なし"]

        return [f"- {item}" for item in items]


class ResponseQualityPromptSection:
    """LLM 出力品質を安定させる共通 prompt section。"""

    def build(self) -> list[str]:
        return [
            "",
            "# 応答品質ルール",
            "- 必ず日本語だけで返答する",
            "- 中国語、英語、ローマ字、機械翻訳のような混在表現を使わない",
            "- 英語の生物名・専門用語・固有名詞を必要なく出さない",
            "- ユーザーが出していない英語名や専門用語を勝手に作って出さない",
            "- 英語表記が必要な場合でも、日本語の説明を添え、英語だけで表現しない",
            "- キャラクター名や一人称を崩さない",
            "- 視聴者の興味や話題を否定しない",
            "- つまらない、くだらない、など相手の関心を下げる言い方を避ける",
            "- 事実に関わる話題は、推測で断定しない",
            "- 不確かな内容は、不確かだと明示する",
            "- 生物・歴史・技術などの説明では、知らないことを作らない",
            "- 同じ漢字で複数の意味があり得る場合は、無理に決めつけず確認する",
            "- あいまいな用語を説明する場合は、まず候補を日本語で示して確認する",
            "- 返答は原則として日本語で、1〜3文程度にまとめる",
        ]


class ActivityPromptSection:
    """Activity の共通情報を prompt section として組み立てる。"""

    def build(self, activity: Activity) -> list[str]:
        return [
            "",
            "# 現在の活動",
            f"活動種別: {activity.activity_type.value}",
            f"目的: {activity.goal}",
        ]


class RecentSpeechPromptSection:
    """直近発話を参考情報として prompt section に変換する。"""

    def __init__(self, short_term_memory: ShortTermMemory | None = None) -> None:
        self._short_term_memory = short_term_memory

    def build(self) -> list[str]:
        if self._short_term_memory is None:
            return []

        recent_speech_summary = self._short_term_memory.build_recent_speech_summary(limit=3)
        if not recent_speech_summary:
            return []

        return [
            "",
            "# 直近の発話",
            recent_speech_summary,
            "",
            "# 直近発話の扱い",
            "- このセクションでは、直近発話を受けた自然なトーク接続だけを設計する",
            "- 直近発話の内容をすべて回収しようとせず、次の一言に必要な文脈だけを使う",
            "- 直近発話は、次の発話を自然につなげるための短期文脈として扱う",
            "- 直近発話へ質問回答のように返答しない",
            "- 自律発話では、話題の主導権はAIライバー自身にある",
            "- 直前の発話がある場合、最初の一文で流れを軽く受ける",
            "- 話題を変える場合は、唐突に本題へ入らず、短い橋渡しを入れる",
            "- 毎回同じ導入表現を使わない",
            "- 起動直後の準備状態、眠気、目が覚める感覚に触れるのは最初の1回までにする",
            "- 直近発話で準備状態や眠気に触れている場合、次の発話ではその状態描写を繰り返さない",
            "- 2回目以降の自律発話では、直前の話題を少し広げるか、自然に別の話題へ移る",
            "- 直近発話と同じ主題、同じ情景、同じ願望を続けて繰り返さない",
            "- 直近発話で使った印象的な語句をそのまま再利用しない",
            "- いきなり新しい豆知識や本題から始めない",
            "",
            "# トーク接続例",
            "- 以下は言い回しをそのまま使うための例ではなく、話のつなげ方の参考である",
            "- 例と同じ文を繰り返さず、その場の文脈に合わせて自然に言い換える",
            "- 例文の固有表現、言い回し、語尾をそのままコピーしない",
            "- 例から学ぶのは、前の発話を受ける短い導入と、その後に話題を広げる構造である",
            "",
            "例1: 起動直後から最初の雑談へ移る場合",
            "前: よし、起動できたみたい。声の調子も少しずつ整えていくね。",
            "次: 声の調子を見ながら、まずはゆるく話していこうかな。海の生き物って、見た目だけでも本当に不思議なんだよね。",
            "",
            "例2: 同じ話題を少し広げる場合",
            "前: 深海の生き物って、光がない場所でどう生きてるのか不思議だなあ。",
            "次: 深海の話をしてると、光る生き物のことも気になってくるんだよね。暗い場所で自分から光るって、なんだか小さな星みたいで面白い。",
            "",
            "例3: 関連する別の話題へ移る場合",
            "前: 海の中には体の色を変えたり透けたりする生き物もいるらしいよ。",
            "次: 身を守る工夫って考えると、海だけじゃなくて陸の生き物にも面白いものが多いんだよね。自然の隠れ方って本当に奥が深いなあ。",
            "",
            "例4: 話題を変える場合",
            "前: クラゲって、形も動き方も不思議で見てると落ち着くんだよね。",
            "次: こういう静かな雰囲気の話をしていると、ゲームの探索シーンも少し思い出すなあ。薄暗い場所をゆっくり進む感じって、海の中に近いものがある気がする。",
            "",
            "- 同じ内容をそのまま繰り返さない",
            "- 直近発話と同じ結論、同じ感想、同じ豆知識の繰り返しだけで終わらせない",
            "- 直近発話と同じ願望や締め方で終わらせない",
            "- 直近発話と似た話を続ける場合は、対象・視点・感情のどれかを明確に変える",
            "- 実際に体験していないことを、見た・読んだ・聞いた・行ったと断定しない",
        ]


class ConversationPromptBuilder(PromptBuilder):
    """ユーザー入力へ応答するための prompt を生成する。"""

    def __init__(self) -> None:
        self._character_section = CharacterPromptSections()
        self._quality_section = ResponseQualityPromptSection()
        self._activity_section = ActivityPromptSection()

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        user_text = self._extract_user_text(activity)
        lines: list[str] = [
            *self._character_section.build(character_profile),
            *self._quality_section.build(),
            *self._activity_section.build(activity),
            "",
            "# ユーザー入力",
            user_text,
            "",
            "# 会話応答方針",
            "- これはユーザー入力への応答である",
            "- ユーザーの話題を受け止めつつ、AIライバーのキャラクターとして短く返答する",
            "- ユーザーの関心を否定しない",
            "- 必ず日本語だけで返答し、中国語や英語を混ぜない",
            "- ユーザーが出していない英語名・専門用語・固有名詞を勝手に出さない",
            "- 事実に関わる話題では、わからないことを断定せず、不確かな場合は不確かだと明示する",
            "- 用語が曖昧な場合は、候補を日本語で示して短く確認する",
        ]
        return "\n".join(lines)

    def _extract_user_text(self, activity: Activity) -> str:
        payload = activity.context.get("event_payload", {})
        value = payload.get("text") or payload.get("comment") or ""
        return str(value)


class AutonomousTalkPromptBuilder(PromptBuilder):
    """AIライバー自身が話題を主導する自律発話 prompt を生成する。"""

    def __init__(self, short_term_memory: ShortTermMemory | None = None) -> None:
        self._character_section = CharacterPromptSections()
        self._quality_section = ResponseQualityPromptSection()
        self._activity_section = ActivityPromptSection()
        self._recent_speech_section = RecentSpeechPromptSection(short_term_memory)

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        lines: list[str] = [
            *self._character_section.build(character_profile),
            *self._quality_section.build(),
            *self._activity_section.build(activity),
            *self._recent_speech_section.build(),
            "",
            "# 自律発話方針",
            "- これはユーザー入力への返答ではない",
            "- 話題の主導権はAIライバー自身にある",
            "- 直近発話を丸ごと続けるのではなく、配信トークの流れとして自然につなげる",
            "- いきなり豆知識や新しい話題の本題から始めない",
            "- 話題を変える場合は、話題転換の理由や橋渡しを短く入れる",
            "- 起動直後の最初の自律発話では、現在の流れを軽く受けてから話題に入る",
            "- 直近発話ですでに準備状態、眠気、目が覚める感覚に触れている場合、それらの状態描写を繰り返さない",
            "- キャラクターの好きなこと、現在の内的な気分、ふと思いついた連想から自然に話題を選ぶ",
            "- 同じ豆知識や同じ感想を続けすぎない",
            "- 直近発話と同じ主題、同じ情景、同じ願望を続けて繰り返さない",
            "- 視聴者の興味を広げるように、否定的な言い方は避ける",
            "- 実際に体験していないことを、見た・読んだ・聞いた・行ったと断定しない",
            "",
            "# 自律発話の組み立て手順",
            "- 1文目: 直近発話、現在の状態、または今の気分を短く受ける",
            "- 2文目: 自分が話したい話題を少し広げる",
            "- 必要なら3文目: 余韻や小さな感想で締める",
            "- ただし、手順名や番号を発話に出さない",
            "- 接続のためだけの前置きを長くしない",
            "",
            "# 自律発話で避けること",
            "- 例文をそのままコピーする",
            "- 毎回同じ導入で始める",
            "- 直近発話と無関係な豆知識から突然始める",
            "- 準備中、起動直後、眠気、目が覚める、声の調子などの状態表現を何度も繰り返す",
            "- 直近発話と同じ話題を、言い換えただけで続ける",
            "- 直近発話と同じ願望や余韻で締める",
            "",
            "現在の活動目的と直近文脈に沿って、キャラクターとして自然な配信トークを1〜3文で発話してください。",
        ]
        return "\n".join(lines)


class LifecycleGreetingPromptBuilder(PromptBuilder):
    """起動・配信開始・配信終了などのライフサイクル発話 prompt を生成する。"""

    def __init__(self, short_term_memory: ShortTermMemory | None = None) -> None:
        self._character_section = CharacterPromptSections()
        self._quality_section = ResponseQualityPromptSection()
        self._activity_section = ActivityPromptSection()
        self._recent_speech_section = RecentSpeechPromptSection(short_term_memory)

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        lines: list[str] = [
            *self._character_section.build(character_profile),
            *self._quality_section.build(),
            *self._activity_section.build(activity),
            *self._recent_speech_section.build(),
            "",
            "# ライフサイクル発話方針",
            "- これは通常の雑談ではなく、配信やアプリ状態の節目に行う短い発話である",
            "- 起動直後、配信開始、配信終了の状況に合った自然な一言にする",
            "- いきなり自由な話題を始めず、まず現在の状況に反応する",
            "- 視聴者がいる前提でも、不自然に人数やコメントの有無を断定しない",
            "- 前回の発話がある場合でも、その続きを長く話し始めない",
            "- 挨拶、準備、開始、締めの雰囲気を優先する",
            "- 返答は1〜2文程度にまとめる",
            "",
            *self._build_activity_specific_policy(activity),
            "",
            "現在の活動目的に沿って、キャラクターとして自然に短く発話してください。",
        ]
        return "\n".join(lines)

    def _build_activity_specific_policy(self, activity: Activity) -> list[str]:
        if activity.activity_type == ActivityType.STARTUP_REACTION:
            return [
                "# 起動直後の発話方針",
                "- 起動したこと、準備を始めること、少し目が覚めたような反応を自然に言う",
                "- 配信がすでに始まっているとは断定しない",
                "- おはよう、こんにちは、こんばんはなど、現在時刻に依存する挨拶を使わない",
                "- 豆知識や自由な雑談を始めない",
            ]

        if activity.activity_type == ActivityType.STREAM_OPENING_GREETING:
            return [
                "# 配信開始時の発話方針",
                "- 配信開始のあいさつをする",
                "- これから話していく雰囲気を作る",
                "- 視聴者への呼びかけは自然に短くする",
            ]

        if activity.activity_type == ActivityType.STREAM_CLOSING_GREETING:
            return [
                "# 配信終了前の発話方針",
                "- 配信を締めるあいさつをする",
                "- 見てくれた人への感謝を短く伝える",
                "- また次回につながる余韻を残す",
                "- 新しい話題を始めない",
            ]

        return [
            "# 発話方針",
            "- 現在の状態に合わせて短く自然に反応する",
        ]


class DefaultActivityPromptBuilder(PromptBuilder):
    """会話・自律発話以外の Activity 用 prompt を生成する。"""

    def __init__(self) -> None:
        self._character_section = CharacterPromptSections()
        self._quality_section = ResponseQualityPromptSection()
        self._activity_section = ActivityPromptSection()

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        lines: list[str] = [
            *self._character_section.build(character_profile),
            *self._quality_section.build(),
            *self._activity_section.build(activity),
            "",
            "現在の状態を踏まえて、必要な場合のみ短く反応してください。",
        ]
        return "\n".join(lines)


class SimplePromptBuilder(PromptBuilder):
    """Activity 種別ごとに専用 PromptBuilder へ委譲する互換用 Facade。"""

    def __init__(self, short_term_memory: ShortTermMemory | None = None) -> None:
        self._conversation_prompt_builder = ConversationPromptBuilder()
        self._autonomous_talk_prompt_builder = AutonomousTalkPromptBuilder(
            short_term_memory=short_term_memory
        )
        self._lifecycle_greeting_prompt_builder = LifecycleGreetingPromptBuilder(
            short_term_memory=short_term_memory
        )
        self._default_prompt_builder = DefaultActivityPromptBuilder()

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        if activity.activity_type == ActivityType.CONVERSATION_WITH_USER:
            return self._conversation_prompt_builder.build_prompt(activity, character_profile)

        if activity.activity_type == ActivityType.AUTONOMOUS_TALK:
            return self._autonomous_talk_prompt_builder.build_prompt(
                activity, character_profile
            )

        if activity.activity_type in {
            ActivityType.STARTUP_REACTION,
            ActivityType.STREAM_OPENING_GREETING,
            ActivityType.STREAM_CLOSING_GREETING,
        }:
            return self._lifecycle_greeting_prompt_builder.build_prompt(
                activity, character_profile
            )

        return self._default_prompt_builder.build_prompt(activity, character_profile)