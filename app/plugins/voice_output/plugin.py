from __future__ import annotations

import logging

from app.shared.contracts.expression import VoiceIntent
from app.shared.contracts.output import AudioPlayer, SpeechSynthesizer
from app.shared.contracts.plugins.runtime import CapabilityReporter, PluginContext


class VoiceOutputPlugin:
    """音声合成と再生を一つの任意Capabilityとして隔離するPlugin。"""

    plugin_id = "voice_output"
    display_name = "Voice Output"
    SPEECH_CAPABILITY = "output.speech"

    def __init__(
        self,
        synthesizer: SpeechSynthesizer | None,
        player: AudioPlayer | None,
    ) -> None:
        self._synthesizer = synthesizer
        self._player = player
        self._initialized = False
        self._healthy = False
        self._capability_reporter: CapabilityReporter | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({self.SPEECH_CAPABILITY})

    def available_capabilities(self) -> frozenset[str]:
        if self._initialized and self._healthy:
            return self.capabilities
        return frozenset()

    def initialize(self, context: PluginContext) -> None:
        self._capability_reporter = context.capability_reporter
        self._initialized = True
        self._healthy = self._synthesizer is not None and self._player is not None
        self._logger.info("voice output initialized: available=%s", self._healthy)

    def shutdown(self) -> None:
        self._initialized = False
        self._healthy = False
        self._capability_reporter = None

    async def synthesize(
        self,
        text: str,
        voice_intent: VoiceIntent | None = None,
    ) -> bytes:
        if not self._initialized or not self._healthy or self._synthesizer is None:
            raise RuntimeError("voice_output.synthesis_unavailable")
        try:
            return await self._synthesizer.synthesize(text, voice_intent=voice_intent)
        except Exception as error:
            self._mark_unavailable("synthesis_failed", error)
            raise

    async def play(self, audio_data: bytes) -> None:
        if not self._initialized or not self._healthy or self._player is None:
            raise RuntimeError("voice_output.playback_unavailable")
        try:
            await self._player.play(audio_data)
        except Exception as error:
            # Webブラウザの一時的な切断、再生拒否、タイムアウトは、
            # 音声合成Capability自体の恒久的な故障を意味しない。
            # 次の発話で再試行できるよう、利用可能状態は維持する。
            self._logger.warning(
                "voice output playback failed; keeping capability available: "
                "capability=%s error=%s",
                self.SPEECH_CAPABILITY,
                type(error).__name__,
            )
            raise

    def _mark_unavailable(self, reason: str, error: Exception) -> None:
        self._healthy = False
        if self._capability_reporter is not None:
            self._capability_reporter.set_capability_availability(
                self.plugin_id,
                self.SPEECH_CAPABILITY,
                available=False,
            )
        self._logger.warning(
            "voice output capability lost: capability=%s reason=%s error=%s",
            self.SPEECH_CAPABILITY,
            reason,
            type(error).__name__,
        )
