from __future__ import annotations

from app.domain.activities import Activity
from app.ports.response_generator import ResponseGenerator
from app.shared.testing import STREAMING_DEMO_SPEECH


class StreamingDemoResponseGenerator(ResponseGenerator):
    """ローカル配信デモ専用のCore ResponseGenerator Adapter。"""

    async def generate_response(self, activity: Activity) -> str:
        return STREAMING_DEMO_SPEECH.get(
            activity.activity_type.value,
            "ローカル配信テストを確認しています。",
        )
