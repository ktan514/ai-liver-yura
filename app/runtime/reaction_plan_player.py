from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from app.domain.character_response import ReactionPlan, ReactionSegment
from app.shared.contracts.output import AudioPlayer, SpeechSynthesizer
from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class PreparedReactionSegment:
    index: int
    segment: ReactionSegment
    audio_data: bytes


class ReactionPlanPlayer:
    """ReactionSegmentを先読みし、順序を守って継ぎ目なく再生する。"""

    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        player: AudioPlayer,
        *,
        max_prefetch_concurrency: int = 2,
    ) -> None:
        if max_prefetch_concurrency <= 0:
            raise ValueError("max_prefetch_concurrency は1以上にしてください。")
        self._synthesizer = synthesizer
        self._player = player
        self._semaphore = asyncio.Semaphore(max_prefetch_concurrency)
        self._trace_logger = TraceLogger()

    async def play(
        self,
        reaction_plan: ReactionPlan,
        *,
        canceled: Callable[[], bool] | None = None,
    ) -> int:
        """再生済みsegment数を返す。未開始segmentは安全に破棄できる。"""

        cancel_requested = canceled or (lambda: False)
        tasks = [
            asyncio.create_task(self._prepare(index, segment))
            for index, segment in enumerate(reaction_plan.segments)
        ]
        completed = 0
        try:
            for index, task in enumerate(tasks):
                if cancel_requested():
                    self._cancel_pending(tasks[index:])
                    break
                prepared = await task
                if cancel_requested():
                    self._cancel_pending(tasks[index:])
                    break
                await self._player.play(prepared.audio_data)
                completed += 1
                pause = prepared.segment.pause_after_seconds
                if pause > 0.0:
                    await asyncio.sleep(pause)
        finally:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._trace_logger.info(
            "reaction_plan_player:finished",
            segment_count=len(reaction_plan.segments),
            completed_segment_count=completed,
            canceled=completed < len(reaction_plan.segments),
        )
        return completed

    async def _prepare(
        self,
        index: int,
        segment: ReactionSegment,
    ) -> PreparedReactionSegment:
        async with self._semaphore:
            audio_data = await self._synthesizer.synthesize(
                segment.speech,
                voice_intent=segment.voice_intent,
            )
        return PreparedReactionSegment(
            index=index,
            segment=segment,
            audio_data=audio_data,
        )

    @staticmethod
    def _cancel_pending(tasks: list[asyncio.Task[PreparedReactionSegment]]) -> None:
        for task in tasks:
            if not task.done():
                task.cancel()
