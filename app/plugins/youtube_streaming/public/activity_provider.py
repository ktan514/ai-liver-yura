from __future__ import annotations

from uuid import uuid4

from app.core.contracts.plugins import PluginActivityRequest
from app.domain.activities import Activity, ActivityType
from app.domain.trace_context import TraceContext


class StreamingActivityProvider:
    async def create_activity(self, request: PluginActivityRequest) -> Activity:
        definitions = {
            "stream.activity.opening": (
                ActivityType.STREAM_OPENING_GREETING,
                "配信開始時のあいさつをして、これから話し始める雰囲気を作る",
                195,
            ),
            "stream.activity.main": (
                ActivityType.STREAM_MAIN_SEGMENT,
                "進行表の本編意図に沿って1回だけ話す",
                194,
            ),
            "stream.activity.comment_response": (
                ActivityType.STREAM_COMMENT_RESPONSE,
                "予約済みの安全化された視聴者コメントへ短く返答する",
                193,
            ),
            "stream.activity.closing": (
                ActivityType.STREAM_CLOSING_GREETING,
                "配信終了前のあいさつをして自然に別れを伝える",
                230,
            ),
        }
        definition = definitions.get(request.capability)
        if definition is None:
            raise ValueError(f"Unsupported streaming activity: {request.capability}")
        activity_type, goal, priority = definition
        return Activity(
            activity_type=activity_type,
            goal=goal,
            priority=priority,
            context={
                "event_payload": dict(request.payload),
                "trace_context": TraceContext(trace_id=request.trace_id),
            },
            interruptible=False,
            source_event_id=str(uuid4()),
        )

