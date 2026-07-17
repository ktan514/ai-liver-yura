from __future__ import annotations

from app.domain.emotions import EmotionState


class FakeSpeechSynthesizer:
    """Demo synthesizer that never performs network or device I/O."""

    async def synthesize(self, text: str, emotion: EmotionState | None = None) -> bytes:
        del emotion
        return f"DEMO_AUDIO:{text}".encode()


class FakeAudioPlayer:
    """Demo player that completes immediately without producing sound."""

    async def play(self, audio_data: bytes) -> None:
        del audio_data
