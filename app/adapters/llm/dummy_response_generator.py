

from __future__ import annotations

from app.domain.activities import Activity, ActivityType
from app.runtime.response_generator import ResponseGenerator


class DummyResponseGenerator(ResponseGenerator):
    """LLM接続前の仮応答生成アダプタ。"""

    async def generate_response(self, activity: Activity) -> str:
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