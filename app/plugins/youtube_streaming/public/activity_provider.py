from __future__ import annotations

from uuid import uuid4

from app.shared.contracts.plugins.registration import (
    PluginActivityRequest,
    PluginActivitySpec,
)


class StreamingActivityProvider:
    async def create_activity(
        self, request: PluginActivityRequest
    ) -> PluginActivitySpec:
        definitions = {
            "stream.activity.opening": (
                "stream_opening_greeting",
                "配信開始時のあいさつをして、これから話し始める雰囲気を作る",
                195,
            ),
            "stream.activity.main": (
                "stream_main_segment",
                "進行表の本編意図に沿って1回だけ話す",
                194,
            ),
            "stream.activity.comment_response": (
                "stream_comment_response",
                "予約済みの安全化された視聴者コメントへ短く返答する",
                193,
            ),
            "stream.activity.closing": (
                "stream_closing_greeting",
                "配信終了前のあいさつをして自然に別れを伝える",
                230,
            ),
        }
        definition = definitions.get(request.capability)
        if definition is None:
            raise ValueError(f"Unsupported streaming activity: {request.capability}")
        activity_type, goal, priority = definition
        return PluginActivitySpec(
            activity_type=activity_type,
            goal=goal,
            priority=priority,
            context={
                "event_payload": dict(request.payload),
            },
            interruptible=False,
            source_event_id=str(uuid4()),
            trace_id=request.trace_id,
        )
