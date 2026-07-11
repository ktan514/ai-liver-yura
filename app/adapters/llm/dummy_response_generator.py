from __future__ import annotations

from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.ports.prompt_builder import PromptBuilder
from app.ports.response_generator import ResponseGenerator


class DummyResponseGenerator(ResponseGenerator):
    """LLM接続前の仮応答生成アダプタ。"""

    def __init__(
        self,
        character_profile: CharacterProfile,
        prompt_builder: PromptBuilder,
    ) -> None:
        self._character_profile = character_profile
        self._prompt_builder = prompt_builder
        self.latest_prompt: str | None = None

    async def generate_response(self, activity: Activity) -> str:
        self.latest_prompt = self._prompt_builder.build_prompt(
            activity=activity,
            character_profile=self._character_profile,
        )

        if activity.activity_type == ActivityType.CONVERSATION_WITH_USER:
            text = self._extract_user_text(activity)
            return f"ダミー応答: {text}"

        if activity.activity_type == ActivityType.AUTONOMOUS_TALK:
            return "ダミー自律発話: 何か面白い話題を考えています。"

        return "ダミー観察応答"

    def _extract_user_text(self, activity: Activity) -> str:
        payload = activity.context.get("event_payload", {})
        value = payload.get("text") or payload.get("comment") or ""
        return str(value)