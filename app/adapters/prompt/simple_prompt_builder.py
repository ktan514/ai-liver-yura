from __future__ import annotations

from app.adapters.prompt.topic_history_prompt_section import TopicHistoryPromptSection
from app.adapters.prompt.topic_memory_prompt_section import TopicMemoryPromptSection
from app.domain.activities import Activity, ActivityType, OngoingActivity
from app.domain.character import CharacterProfile
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicHistory
from app.domain.topic_memory import SimilarTopicMemory
from app.ports.prompt_builder import PromptBuilder


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
        lines = [
            "",
            "# 現在の活動",
            f"活動種別: {activity.activity_type.value}",
            f"目的: {activity.goal}",
        ]
        if activity.activity_type == ActivityType.GAME_WITH_USER:
            lines.extend(
                [
                    "",
                    "# GameSession",
                    f"session_id: {activity.context.get('game_session_id')}",
                    f"game_type: {activity.context.get('game_type')}",
                    f"status: {activity.context.get('game_status')}",
                    f"current_turn: {activity.context.get('game_current_turn')}",
                    f"metadata: {activity.context.get('game_metadata', {})}",
                ]
            )
            if activity.context.get("game_type") == "shiritori":
                lines.extend(self._build_shiritori_lines(activity))
        return lines

    @staticmethod
    def _build_shiritori_lines(activity: Activity) -> list[str]:
        action = activity.context.get("shiritori_action")
        lines = [
            "",
            "# しりとり状態",
            f"現在の手番: {activity.context.get('current_turn')}",
            f"直前の単語: {activity.context.get('last_word')}",
            f"必要な開始文字: {activity.context.get('expected_head')}",
            f"使用済み単語: {activity.context.get('used_words', [])}",
            f"ターン数: {activity.context.get('turn_count')}",
            f"入力検証結果: {activity.context.get('validation_result')}",
            f"勝者: {activity.context.get('winner')}",
            f"敗者: {activity.context.get('loser')}",
            f"終了理由: {activity.context.get('end_reason')}",
            f"現在の感情: {activity.context.get('emotion')}",
            "",
            "# しりとり共通ルール",
            "- 前の単語の最後の文字から始まる日本語の単語を使う",
            "- 『ん』で終わる単語を選ばない",
            "- 使用済みの単語を使わない",
            "- 不自然な造語を避ける",
            "- ゲーム進行を妨げる長文を避け、ゆらの人格と現在の感情に合う短い発話にする",
        ]
        if action == "generate_ai_word":
            lines.extend(
                [
                    "",
                    "# 出力形式",
                    "次のJSONオブジェクトだけを出力する。Markdownや説明文を付けない。",
                    '{"game_action":"play_word","word":"単語","utterance":"実際に発話する短い文章"}',
                    "- wordには判定対象の単語だけを入れる",
                    "- utteranceにはwordを含むキャラクターらしい短い発話を入れる",
                ]
            )
        return lines


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
            "- いきなり新しい豆知識や本題から始めない",
            "",
            "# 反復・滞留防止",
            "- 起動直後の準備状態、眠気、目が覚める感覚に触れるのは最初の1回までにする",
            "- 直近発話で準備状態や眠気に触れている場合、次の発話ではその状態描写を繰り返さない",
            "- 2回目以降の自律発話では、直前の話題を少し広げるか、自然に別の話題へ移る",
            "- 直近発話と同じ主題、同じ情景、同じ願望を続けて繰り返さない",
            "- 直近発話で使った印象的な語句をそのまま再利用しない",
            "- 同じ大テーマに留まり続けず、2〜3発話続いたら別カテゴリへ自然に移る",
            "- 話題を変える場合は、直前の話題との共通点を1つ使って橋渡しする",
            "- 細部を掘り続けるだけでなく、別カテゴリへ広げる",
            "- 同じ内容をそのまま繰り返さない",
            "- 直近発話と同じ結論、同じ感想、同じ豆知識の繰り返しだけで終わらせない",
            "- 直近発話と同じ願望や締め方で終わらせない",
            "- 直近発話と似た話を続ける場合は、対象・視点・感情のどれかを明確に変える",
            "",
            "# 視聴者への開き方",
            "- 視聴者へ開く一言はたまに入れる程度にし、毎回質問で終わらせない",
            "- 視聴者に問いかける場合は、答えやすい軽い問いにする",
            "- コメントが来ているとは断定しない",
            "",
            "# 事実性の扱い",
            "- 実際に体験していないことを、見た・読んだ・聞いた・行ったと断定しない",
            "- 不確かな話題は、〜らしい、〜と言われている、〜を想像すると、のように表現する",
            "",
            "# トーク接続例",
            "- 以下は言い回しをそのまま使うための例ではなく、話のつなげ方の参考である",
            "- 例と同じ文を繰り返さず、その場の文脈に合わせて自然に言い換える",
            "- 例文の固有表現、言い回し、語尾をそのままコピーしない",
            "- 例から学ぶのは、前の発話を受ける短い導入と、その後に話題を広げる構造である",
            "",
            "例1: 起動直後から最初の雑談へ移る場合",
            "前: よし、起動できたみたい。声の調子も少しずつ整えていくね。",
            "次: 声の調子を見ながら、まずはゆるく話していこうかな。"
            "海の生き物って、見た目だけでも本当に不思議なんだよね。",
            "",
            "例2: 同じ話題を少し広げる場合",
            "前: 深海の生き物って、光がない場所でどう生きてるのか不思議だなあ。",
            "次: 深海の話をしてると、光る生き物のことも気になってくるんだよね。"
            "暗い場所で自分から光るって、なんだか小さな星みたいで面白い。",
            "",
            "例3: 関連する別の話題へ移る場合",
            "前: 海の中には体の色を変えたり透けたりする生き物もいるらしいよ。",
            "次: 身を守る工夫って考えると、海だけじゃなくて陸の生き物にも"
            "面白いものが多いんだよね。自然の隠れ方って本当に奥が深いなあ。",
            "",
            "例4: 話題を変える場合",
            "前: クラゲって、形も動き方も不思議で見てると落ち着くんだよね。",
            "次: こういう静かな雰囲気の話をしていると、ゲームの探索シーンも少し"
            "思い出すなあ。薄暗い場所をゆっくり進む感じって、海の中に近いものがある気がする。",
            "",
            "例5: 同じ大テーマが続いた後に別カテゴリへ移る場合",
            "前: 潮が引いた岩場って、小さな隙間に生き物の世界が広がってる感じがするよね。",
            "次: こういう小さな発見の話をしていると、探索ゲームで隠し通路を"
            "見つけた時の感じも思い出すなあ。見逃しそうな場所に何かあるかも、"
            "って思う瞬間が好きなんだよね。",
            "",
            "例6: 視聴者へ軽く開く場合",
            "前: 水族館のクラゲって、ゆっくり見ていると時間を忘れそうになるよね。",
            "次: クラゲみたいに静かに見ていたくなる生き物って、みんなにもあるのかな。"
            "私はああいうふわっとした動きを見てると、少し気持ちが落ち着くんだよね。",
        ]


class RelatedTopicMemoryPromptSection:
    """検索済みの長期記憶を参考情報として prompt section に変換する。"""

    def __init__(self) -> None:
        self._topic_memory_prompt_section = TopicMemoryPromptSection()

    def build(self, activity: Activity) -> list[str]:
        similar_topic_memories = self._extract_similar_topic_memories(activity)
        prompt_section = self._topic_memory_prompt_section.build(similar_topic_memories)
        if not prompt_section:
            return []

        return [
            "",
            prompt_section,
            "",
            "# 関連記憶の扱い",
            "- このセクションは、過去に話した内容を自然に思い出すための参考情報である",
            "- 関連記憶をそのまま読み上げず、必要な要素だけを会話の流れに溶け込ませる",
            "- 記憶にない具体的な体験を、実際に体験したこととして断定しない",
            "- 関連性が低い場合は無理に使わない",
        ]

    def _extract_similar_topic_memories(self, activity: Activity) -> list[SimilarTopicMemory]:
        value = activity.context.get("similar_topic_memories", [])
        if not isinstance(value, list):
            return []

        return [item for item in value if isinstance(item, SimilarTopicMemory)]


class ConversationPromptBuilder(PromptBuilder):
    """ユーザー入力へ応答するための prompt を生成する。"""

    def __init__(self) -> None:
        self._character_section = CharacterPromptSections()
        self._quality_section = ResponseQualityPromptSection()
        self._activity_section = ActivityPromptSection()

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        user_text = self._extract_user_text(activity)
        ongoing_activity_lines = self._build_ongoing_activity_section(activity)
        game_input_lines = self._build_game_input_section(activity)
        plugin_lines = self._build_plugin_capability_section(activity)
        lines: list[str] = [
            *self._character_section.build(character_profile),
            *self._quality_section.build(),
            *self._activity_section.build(activity),
            "",
            "# ユーザー入力",
            user_text,
            *plugin_lines,
            *game_input_lines,
            *ongoing_activity_lines,
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

    def _build_plugin_capability_section(self, activity: Activity) -> list[str]:
        payload = activity.context.get("event_payload", {})
        if not isinstance(payload, dict):
            return []
        capabilities = payload.get("available_plugin_capabilities", [])
        contexts = payload.get("plugin_contexts", [])
        behavior_plan = payload.get("behavior_plan")
        behavior_result = payload.get("behavior_plan_result")
        behavior_fallback = payload.get("behavior_fallback_plan")
        lines = [
            "",
            "# 現在の行為実行に関する事実（内部情報）",
            f"現在使用可能と確認済みの実行候補: {capabilities}",
            f"行為が実行済みか: {payload.get('execution_performed', False)}",
        ]
        if contexts:
            lines.append(f"実行判断の補足: {contexts}")
        if behavior_plan:
            lines.append(f"Behavior PlannerのActivity Plan: {behavior_plan}")
        if behavior_result:
            lines.append(f"Activity Planの検証・実行Result: {behavior_result}")
        if behavior_fallback:
            lines.append(f"拒否Resultを受けた再判断: {behavior_fallback}")
        if payload.get("execution_request_unmatched"):
            lines.extend(
                [
                    "- ユーザーは何らかの行為の実行を望んでいるが、"
                    "現在使用可能な実行候補とは一致しなかった",
                    "- 要求された行為を、開始・取得・操作・登録・確認・視認・聴取したように"
                    "表現してはいけない",
                    "- 誘いや気持ちは受け止め、今は実行できない事実を"
                    "キャラクターらしく短く自然に伝える",
                    "- Plugin、Capability、Providerなど内部構成を示す語を返答に出してはいけない",
                    "- 将来できるようになるとは約束しない",
                    "- 話題についての知識説明や感想まで拒否してはいけない",
                    "- 代替案は、下記に明記された現在可能なものから最大一つだけ。"
                    "なければ提案しない",
                    f"- 現在可能な代替: {payload.get('available_alternative')}",
                ]
            )
        else:
            lines.append(
                "- 実行済みの明確な事実がない行為を、実行・取得・確認などしたように"
                "表現してはいけない"
            )
        return lines

    def _build_game_input_section(self, activity: Activity) -> list[str]:
        payload = activity.context.get("event_payload", {})
        if not isinstance(payload, dict):
            return []
        classification = payload.get("game_input_classification")
        game_context = payload.get("game_session_context")
        if classification is None or not isinstance(game_context, dict):
            return []
        classification_value = getattr(classification, "classification", None)
        classification_name = getattr(classification_value, "value", classification_value)
        return [
            "",
            "# ゲーム入力の分類結果",
            f"分類: {classification_name}",
            f"分類理由: {getattr(classification, 'reason', '')}",
            f"確認が必要: {payload.get('confirmation_required', False)}",
            f"ゲーム種別: {game_context.get('game_type')}",
            f"ゲーム状態: {game_context.get('game_status')}",
            f"現在の手番: {game_context.get('current_turn')}",
            f"直前の単語: {game_context.get('last_word')}",
            f"次に必要な文字: {game_context.get('expected_head')}",
            f"開始失敗: {payload.get('game_start_failed', False)}",
            f"開始失敗理由: {payload.get('failure_reason')}",
            f"要求ゲーム: {payload.get('requested_game')}",
            f"対応済み: {payload.get('supported')}",
            f"対応ゲーム一覧: {payload.get('supported_games', [])}",
            "- 会話へ応答しても、ここではゲーム状態を変更しない",
            "- ambiguousで確認が必要なら、ゲーム入力か通常会話かを短く確認する",
            "- unsupported_game_requestなら、対応ゲームを案内しつつ通常会話として返す",
        ]

    def _build_ongoing_activity_section(self, activity: Activity) -> list[str]:
        ongoing = activity.context.get("ongoing_activity")
        if not isinstance(ongoing, OngoingActivity):
            return []
        return [
            "",
            "# 継続中の複数ターン活動",
            f"活動ID: {ongoing.ongoing_activity_id}",
            f"活動種別: {ongoing.activity_type}",
            f"状態: {ongoing.status.value}",
            f"開始時の目的: {ongoing.goal}",
            "直前のActivity結果種別: "
            f"{ongoing.last_result.result_type if ongoing.last_result else 'なし'}",
            f"直前のActivity結果: {ongoing.last_result.summary if ongoing.last_result else 'なし'}",
            f"次に期待する入力: {ongoing.expected_input}",
            f"終了条件: {ongoing.end_condition}",
            "- 今回の入力は通常会話ではなく、この活動を継続する入力として扱う",
            "- 終了条件を満たす場合は、活動を自然に締める応答にする",
        ]

    def _extract_user_text(self, activity: Activity) -> str:
        payload = activity.context.get("event_payload", {})
        value = payload.get("text") or payload.get("comment") or ""
        return str(value)


class AutonomousTalkPromptBuilder(PromptBuilder):
    """AIライバー自身が話題を主導する自律発話 prompt を生成する。"""

    def __init__(
        self,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
    ) -> None:
        self._character_section = CharacterPromptSections()
        self._quality_section = ResponseQualityPromptSection()
        self._activity_section = ActivityPromptSection()
        self._recent_speech_section = RecentSpeechPromptSection(short_term_memory)
        self._topic_history_section = TopicHistoryPromptSection(topic_history)
        self._related_topic_memory_section = RelatedTopicMemoryPromptSection()

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        continuation_lines = self._build_topic_continuation_section(activity)
        lines: list[str] = [
            *self._character_section.build(character_profile),
            *self._quality_section.build(),
            *self._activity_section.build(activity),
            *self._recent_speech_section.build(),
            *self._topic_history_section.build(),
            *self._related_topic_memory_section.build(activity),
            *continuation_lines,
            "",
            "# 自律発話方針",
            "- これはユーザー入力への返答ではない",
            "- 話題の主導権はAIライバー自身にある",
            "- 直近発話を丸ごと続けるのではなく、配信トークの流れとして自然につなげる",
            "- いきなり豆知識や新しい話題の本題から始めない",
            "- 話題を変える場合は、話題転換の理由や橋渡しを短く入れる",
            "- 起動直後の最初の自律発話では、現在の流れを軽く受けてから話題に入る",
            "- 直近発話ですでに準備状態、眠気、目が覚める感覚に触れている場合、"
            "それらの状態描写を繰り返さない",
            "- キャラクターの好きなこと、現在の内的な気分、ふと思いついた連想から自然に話題を選ぶ",
            "- 同じ豆知識や同じ感想を続けすぎない",
            "- 直近発話と同じ主題、同じ情景、同じ願望を続けて繰り返さない",
            "- 同じ大テーマが続いている場合は、ゲーム、新しい技術、配信のこと、"
            "今の気分、視聴者に聞いてみたいことへ自然に広げる",
            "- 話題を変える場合は、直前の話題との共通点を短く使って橋渡しする",
            "- 3〜5発話に1回程度、視聴者が答えやすい軽い問いかけを入れてもよい",
            "- ただし、毎回質問で終わらせない",
            "- コメントが来ている、誰かが見ている、などを断定しない",
            "- 視聴者の興味を広げるように、否定的な言い方は避ける",
            "",
            "# 自律発話の組み立て手順",
            "- 1文目: 直近発話、現在の状態、または今の気分を短く受ける",
            "- 2文目: 自分が話したい話題を少し広げる",
            "- 必要なら3文目: 余韻や小さな感想で締める",
            "- ただし、手順名や番号を発話に出さない",
            "- 接続のためだけの前置きを長くしない",
            "- 同じ大テーマが続いている場合は、2文目で別カテゴリへ広げる",
            "- 視聴者へ問いかける場合は、最後の一文で短く添える",
            "",
            "# 自律発話で避けること",
            "- 例文をそのままコピーする",
            "- 毎回同じ導入で始める",
            "- 直近発話と無関係な豆知識から突然始める",
            "- 準備中、起動直後、眠気、目が覚める、声の調子などの状態表現を何度も繰り返す",
            "- 直近発話と同じ話題を、言い換えただけで続ける",
            "- 直近発話と同じ願望や余韻で締める",
            "- 同じ大テーマの細部だけを何度も掘り続ける",
            "- 毎回、観察したい、見てみたい、気になる、ワクワクする、で締める",
            "- コメントが来ている前提で話す",
            "",
            "現在の活動目的と直近文脈に沿って、キャラクターとして自然な配信トークを1〜3文で発話してください。",
        ]
        return "\n".join(lines)

    def _build_topic_continuation_section(self, activity: Activity) -> list[str]:
        payload = activity.context.get("event_payload", {})
        if not isinstance(payload, dict):
            return []
        decision = payload.get("continuation_decision")
        if not isinstance(decision, str):
            return []
        reasons = payload.get("continuation_reasons", [])
        return [
            "",
            "# 中断後の話題進路",
            f"判断: {decision}",
            f"判断理由: {reasons}",
            f"中断前の話題: {payload.get('interrupted_topic') or 'なし'}",
            f"選択した話題: {payload.get('selected_topic') or '新しい話題を選ぶ'}",
            f"再導入が必要: {'はい' if payload.get('reintroduction_required') else 'いいえ'}",
            "- resume_originalまたはresume_with_reframingの場合は、"
            "中断前と同じ内容を繰り返さず続きを話す",
            "- 再導入が必要な場合は、現在の感情と中断理由に合う短い導入を付ける",
            "- branch_from_originalは元話題とのつながりを、branch_from_interruptionは"
            "ユーザー会話とのつながりを短く示す",
            "- start_new_topicでは不要な『さっきの話に戻るけど』を付けない",
        ]


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


class GameInputClassificationPromptBuilder(PromptBuilder):
    """ゲーム前段の入力分類だけを要求する静的Prompt。"""

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        context = activity.context
        return "\n".join(
            [
                "あなたはユーザー入力を分類する前処理器です。",
                "応答文を作らず、指定されたJSONのみ返してください。",
                "",
                f"現在のゲーム: {context.get('game_type')}",
                f"ゲーム状態: {context.get('game_status')}",
                f"現在の手番: {context.get('current_turn')}",
                f"直前の単語: {context.get('last_word')}",
                f"次に必要な文字: {context.get('expected_head')}",
                f"対応ゲーム: {context.get('supported_games', [])}",
                f"ユーザー入力: {context.get('user_text')}",
                "",
                "分類候補:",
                "- game_start_request: 対応ゲームを新しく始める明確な要求",
                "- game_move: ゲームを進める手",
                "- game_control: pause/resume/quit/surrender/restart",
                "- game_chat: ゲームへの質問・感想・訂正・煽り",
                "- normal_chat: ゲームと無関係な通常会話",
                "- mixed: ゲームの手と雑談の両方を含む",
                "- unsupported_game_request: 未対応ゲームの開始要求",
                "- ambiguous: 安全に確定できない",
                "",
                "一語入力を無条件にgame_moveへしない。質問・感想・訂正はgame_chatになり得る。",
                "ゲーム名や開始意図を確定できない場合はgame_start_requestにせずambiguousにする。",
                "mixedではgame_wordとchat_textを分離する。",
                "次のJSONだけを出力する:",
                '{"classification":"ambiguous","confidence":0.0,"game_word":null,"game_control":null,"chat_text":null,"requested_game":null,"reason":"理由"}',
            ]
        )


class SimplePromptBuilder(PromptBuilder):
    """Activity 種別ごとに専用 PromptBuilder へ委譲する互換用 Facade。"""

    def __init__(
        self,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
    ) -> None:
        self._conversation_prompt_builder = ConversationPromptBuilder()
        self._autonomous_talk_prompt_builder = AutonomousTalkPromptBuilder(
            short_term_memory=short_term_memory,
            topic_history=topic_history,
        )
        self._lifecycle_greeting_prompt_builder = LifecycleGreetingPromptBuilder(
            short_term_memory=short_term_memory
        )
        self._default_prompt_builder = DefaultActivityPromptBuilder()
        self._game_input_classification_prompt_builder = GameInputClassificationPromptBuilder()

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        plugin_override = activity.context.get("plugin_prompt_override")
        if isinstance(plugin_override, str):
            return plugin_override
        if activity.activity_type == ActivityType.GAME_INPUT_CLASSIFICATION:
            return self._game_input_classification_prompt_builder.build_prompt(
                activity, character_profile
            )
        if activity.activity_type == ActivityType.CONVERSATION_WITH_USER:
            return self._conversation_prompt_builder.build_prompt(activity, character_profile)

        if activity.activity_type == ActivityType.AUTONOMOUS_TALK:
            return self._autonomous_talk_prompt_builder.build_prompt(activity, character_profile)

        if activity.activity_type in {
            ActivityType.STARTUP_REACTION,
            ActivityType.STREAM_OPENING_GREETING,
            ActivityType.STREAM_CLOSING_GREETING,
        }:
            return self._lifecycle_greeting_prompt_builder.build_prompt(activity, character_profile)

        return self._default_prompt_builder.build_prompt(activity, character_profile)
