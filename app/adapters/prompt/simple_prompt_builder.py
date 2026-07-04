

from __future__ import annotations

from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.runtime import PromptBuilder


class SimplePromptBuilder(PromptBuilder):
    """Activity と CharacterProfile からシンプルな LLM 用 prompt を生成する。"""

    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        lines: list[str] = [
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
            "",
            "# 現在の活動",
            f"活動種別: {activity.activity_type.value}",
            f"目的: {activity.goal}",
        ]

        if activity.activity_type == ActivityType.CONVERSATION_WITH_USER:
            user_text = self._extract_user_text(activity)
            lines.extend(
                [
                    "",
                    "# ユーザー入力",
                    user_text,
                    "",
                    "上記のユーザー入力に対して、キャラクターとして自然に短く返答してください。",
                ]
            )
        elif activity.activity_type == ActivityType.AUTONOMOUS_TALK:
            lines.extend(
                [
                    "",
                    "現在の活動目的に沿って、キャラクターとして自然に短く自律発話してください。",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "現在の状態を踏まえて、必要な場合のみ短く反応してください。",
                ]
            )

        return "\n".join(lines)

    def _format_items(self, items: list[str]) -> list[str]:
        if not items:
            return ["- なし"]

        return [f"- {item}" for item in items]

    def _extract_user_text(self, activity: Activity) -> str:
        payload = activity.context.get("event_payload", {})
        value = payload.get("text") or payload.get("comment") or ""
        return str(value)