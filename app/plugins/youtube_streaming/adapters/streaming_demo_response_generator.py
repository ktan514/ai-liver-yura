from __future__ import annotations

from app.domain.activities import Activity, ActivityType
from app.ports.response_generator import ResponseGenerator

STREAMING_DEMO_RESPONSES = {
    ActivityType.STREAM_OPENING_GREETING: "こんばんは、ゆらです。ローカル配信テストを始めます。",
    ActivityType.STREAM_MAIN_SEGMENT: "今日は配信機能の動作を確認しています。",
    ActivityType.STREAM_COMMENT_RESPONSE: (
        "コメントありがとう。ローカル配信テストへの反応を確認できました。"
    ),
    ActivityType.STREAM_CLOSING_GREETING: (
        "テストに付き合ってくれてありがとう。今日はここまでです。"
    ),
}


class StreamingDemoResponseGenerator(ResponseGenerator):
    """Pure final-speech generator for the local streaming demonstration."""

    async def generate_response(self, activity: Activity) -> str:
        return STREAMING_DEMO_RESPONSES.get(
            activity.activity_type, "ローカル配信テストを確認しています。"
        )
