from __future__ import annotations

import json

from app.domain.activities import Activity
from app.ports.response_generator import ResponseGenerator


class LegacyCharacterModelAdapter:
    """旧ResponseGeneratorの平文を構造化Character Responseへ明示変換する。"""

    def __init__(self, generator: ResponseGenerator) -> None:
        self._generator = generator

    async def generate_character_response(self, activity: Activity) -> str:
        raw_context = activity.context.get("response_context")
        context = raw_context if isinstance(raw_context, dict) else {}
        status = getattr(context.get("status"), "value", context.get("status"))
        summary = str(context.get("result_summary") or "").strip()
        prepared_response = activity.context.get("prepared_response_text")

        if status in {"rejected", "failed", "canceled"}:
            return self._structured(
                "今はそれを一緒にできないんだ。別のお話をしよう。",
                expression="soft_smile",
                claims=["execution_unavailable"],
            )
        if status == "succeeded" and summary:
            # Resultの成功と、発話本文が成功を明言することは別である。
            return self._structured(summary, claims=[])
        if status == "waiting_input" and summary and isinstance(prepared_response, str):
            return self._structured(summary, claims=[])

        raw = await self._generator.generate_response(activity)
        if self._is_character_response(raw):
            return raw
        return self._structured(raw, claims=["conversation_only"])

    @staticmethod
    def _is_character_response(raw: str) -> bool:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return False
        return isinstance(value, dict) and isinstance(value.get("speech"), str)

    @staticmethod
    def _structured(
        speech: str,
        *,
        expression: str = "smile",
        claims: list[str],
    ) -> str:
        return json.dumps(
            {
                "speech": speech,
                "expression": expression,
                "gesture": None,
                "claims": claims,
            },
            ensure_ascii=False,
        )
