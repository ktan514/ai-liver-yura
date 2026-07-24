from datetime import datetime, timezone

import pytest

from app.core.plugins import PluginContext, PluginManager
from app.domain.actions import ActionPlan, ActionType
from app.domain.activities import Activity
from app.domain.activity_turn_result import ActionExecutionStatus
from app.domain.character_response import VoiceIntent
from app.plugins.voice_output import VoiceOutputPlugin
from app.ports.audio_player import AudioPlayer
from app.ports.speech_synthesizer import SpeechSynthesizer
from app.shared.contracts.expression import VoiceIntent as SharedVoiceIntent
from app.shared.contracts.output import (
    AudioPlayer as SharedAudioPlayer,
)
from app.shared.contracts.output import (
    SpeechSynthesizer as SharedSpeechSynthesizer,
)
from app.usecases import ExecuteActionUsecase


def test_legacy_voice_contract_paths_reexport_shared_contracts() -> None:
    assert VoiceIntent is SharedVoiceIntent
    assert AudioPlayer is SharedAudioPlayer
    assert SpeechSynthesizer is SharedSpeechSynthesizer


class StubLlmGateway:
    async def generate_response(self, activity: Activity) -> str:
        return ""


class StubActivityGateway:
    def register(self, activity: Activity) -> Activity:
        return activity


class StubClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeSynthesizer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.received: list[tuple[str, VoiceIntent | None]] = []

    async def synthesize(
        self, text: str, voice_intent: VoiceIntent | None = None
    ) -> bytes:
        self.received.append((text, voice_intent))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return b"audio"


class FakePlayer:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def play(self, audio_data: bytes) -> None:
        self.received.append(audio_data)


def context(manager: PluginManager) -> PluginContext:
    return PluginContext(
        llm_gateway=StubLlmGateway(),
        activity_gateway=StubActivityGateway(),
        clock=StubClock(),
        configuration={},
        capability_reporter=manager,
    )


@pytest.mark.asyncio
async def test_voice_output_plugin_delegates_engine_independent_intent() -> None:
    manager = PluginManager()
    synthesizer = FakeSynthesizer()
    player = FakePlayer()
    plugin = VoiceOutputPlugin(synthesizer, player)
    manager.register(plugin)
    manager.initialize_enabled_plugins(context(manager), {plugin.plugin_id: True})
    intent = VoiceIntent(style="bright")

    audio = await plugin.synthesize("こんにちは", voice_intent=intent)
    await plugin.play(audio)

    assert synthesizer.received == [("こんにちは", intent)]
    assert player.received == [b"audio"]
    assert manager.is_capability_available("output.speech", plugin.plugin_id)


@pytest.mark.asyncio
async def test_voice_output_failure_revokes_capability_without_stopping_core() -> None:
    manager = PluginManager()
    synthesizer = FakeSynthesizer(fail=True)
    plugin = VoiceOutputPlugin(synthesizer, FakePlayer())
    manager.register(plugin)
    manager.initialize_enabled_plugins(context(manager), {plugin.plugin_id: True})

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await plugin.synthesize("こんにちは")

    assert plugin.available_capabilities() == frozenset()
    assert not manager.is_capability_available("output.speech", plugin.plugin_id)

    synthesizer.fail = False
    assert manager.recover_plugin(plugin.plugin_id) is True
    assert await plugin.synthesize("復旧したよ") == b"audio"
    assert manager.is_capability_available("output.speech", plugin.plugin_id)


@pytest.mark.asyncio
async def test_voice_output_failure_keeps_text_fallback_and_returns_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.usecases.execute_action_usecase.asyncio.sleep", no_sleep)
    manager = PluginManager()
    plugin = VoiceOutputPlugin(FakeSynthesizer(fail=True), FakePlayer())
    manager.register(plugin)
    manager.initialize_enabled_plugins(context(manager), {plugin.plugin_id: True})
    usecase = ExecuteActionUsecase(speech_synthesizer=plugin, audio_player=plugin)

    result = await usecase.execute(
        ActionPlan(action_type=ActionType.SPEAK, text="こんにちは")
    )

    assert result is not None
    assert result.status == ActionExecutionStatus.FAILED
    assert not manager.is_capability_available("output.speech", plugin.plugin_id)


def test_voice_output_without_complete_provider_initializes_degraded() -> None:
    manager = PluginManager()
    plugin = VoiceOutputPlugin(None, FakePlayer())
    manager.register(plugin)
    manager.initialize_enabled_plugins(context(manager), {plugin.plugin_id: True})

    assert manager.get_plugin(plugin.plugin_id) is plugin
    assert plugin.available_capabilities() == frozenset()
