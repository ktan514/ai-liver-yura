

from __future__ import annotations

from typing import Protocol

from app.domain.activities import Activity


class ResponseGenerator(Protocol):
    """Activity から応答テキストを生成する Port。"""

    async def generate_response(self, activity: Activity) -> str:
        ...