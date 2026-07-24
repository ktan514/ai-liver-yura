from __future__ import annotations

import json

import pytest

from app.adapters.tts.pronunciation_corrector import PronunciationCorrector
from app.adapters.tts.pronunciation_dictionary import (
    PronunciationDictionary,
    PronunciationRule,
)
from app.adapters.tts.voicevox_speech_synthesizer import (
    VoiceVoxSpeechProfile,
    VoiceVoxSpeechSynthesizer,
    VoiceVoxSpeechSynthesizerConfig,
)
from app.bootstrap.runtime import create_speech_synthesizer
from app.config.app_config import load_app_config
from app.domain.character_response import VoiceIntent


class FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class FakeUrlOpen:
    def __init__(self) -> None:
        self.requests = []
        self.timeouts: list[float] = []

    def __call__(self, http_request, timeout: float):
        self.requests.append(http_request)
        self.timeouts.append(timeout)
        if "/audio_query?" in http_request.full_url:
            return FakeHttpResponse(json.dumps({"speedScale": 1.0}).encode("utf-8"))
        return FakeHttpResponse(b"RIFF-test-wav")


class FailingAudioQueryCorrector:
    def correct(self, *, original_text, corrected_text, audio_query):
        audio_query["unsafe"] = True
        raise RuntimeError("correction failed")


@pytest.mark.asyncio
async def test_synthesize_calls_audio_query_and_synthesis(monkeypatch) -> None:
    fake_urlopen = FakeUrlOpen()
    monkeypatch.setattr(
        "app.adapters.tts.voicevox_speech_synthesizer.request.urlopen",
        fake_urlopen,
    )
    synthesizer = VoiceVoxSpeechSynthesizer(
        VoiceVoxSpeechSynthesizerConfig(
            base_url="http://127.0.0.1:50021/",
            speaker_id=3,
            timeout_seconds=12.0,
            voice_intent_profiles={
                "neutral": VoiceVoxSpeechProfile(0.9, 0.03, 0.9, 1.0),
                "energetic": VoiceVoxSpeechProfile(1.2, 0.1, 1.1, 0.9),
            },
        ),
        pronunciation_corrector=PronunciationCorrector(
            PronunciationDictionary(
                (
                    PronunciationRule(
                        surface="どんな風に",
                        reading="どんなふうに",
                        priority=100,
                        enabled=True,
                        definition_order=0,
                    ),
                )
            )
        ),
    )

    audio_data = await synthesizer.synthesize(
        "どんな風に話そう", voice_intent=VoiceIntent(style="energetic")
    )

    assert audio_data == b"RIFF-test-wav"
    assert len(fake_urlopen.requests) == 2
    assert "/audio_query?" in fake_urlopen.requests[0].full_url
    assert "speaker=3" in fake_urlopen.requests[0].full_url
    assert (
        "%E3%81%A9%E3%82%93%E3%81%AA%E3%81%B5%E3%81%86%E3%81%AB"
        in fake_urlopen.requests[0].full_url
    )
    assert "/synthesis?speaker=3" in fake_urlopen.requests[1].full_url
    synthesis_query = json.loads(fake_urlopen.requests[1].data.decode("utf-8"))
    assert synthesis_query["speedScale"] == 1.2
    assert synthesis_query["pitchScale"] == 0.1
    assert synthesis_query["intonationScale"] == 1.1
    assert synthesis_query["volumeScale"] == 0.9
    assert fake_urlopen.timeouts == [12.0, 12.0]


@pytest.mark.asyncio
async def test_audio_query_correction_failure_uses_original_audio_query(
    monkeypatch,
) -> None:
    fake_urlopen = FakeUrlOpen()
    monkeypatch.setattr(
        "app.adapters.tts.voicevox_speech_synthesizer.request.urlopen",
        fake_urlopen,
    )
    synthesizer = VoiceVoxSpeechSynthesizer(
        VoiceVoxSpeechSynthesizerConfig(
            base_url="http://127.0.0.1:50021",
            speaker_id=89,
        ),
        audio_query_corrector=FailingAudioQueryCorrector(),
    )

    audio_data = await synthesizer.synthesize("こんにちは")

    assert audio_data == b"RIFF-test-wav"
    synthesis_query = json.loads(fake_urlopen.requests[1].data.decode("utf-8"))
    assert "unsafe" not in synthesis_query


@pytest.mark.asyncio
async def test_synthesize_rejects_blank_text() -> None:
    synthesizer = VoiceVoxSpeechSynthesizer(
        VoiceVoxSpeechSynthesizerConfig(
            base_url="http://127.0.0.1:50021",
            speaker_id=3,
        )
    )

    with pytest.raises(ValueError, match="空"):
        await synthesizer.synthesize("  ")


def test_resolve_profile_falls_back_to_default() -> None:
    neutral = VoiceVoxSpeechProfile(0.9, 0.03, 0.9, 1.0)
    synthesizer = VoiceVoxSpeechSynthesizer(
        VoiceVoxSpeechSynthesizerConfig(
            base_url="http://127.0.0.1:50021",
            speaker_id=89,
            voice_intent_profiles={"neutral": neutral},
        )
    )

    profile = synthesizer._resolve_profile(VoiceIntent(style="unknown-style"))

    assert profile == neutral


@pytest.mark.parametrize(
    ("style", "expected_profile"),
    [
        ("neutral", VoiceVoxSpeechProfile(0.90, 0.03, 0.90, 1.00)),
        ("bright", VoiceVoxSpeechProfile(1.02, 0.05, 1.08, 1.03)),
        ("energetic", VoiceVoxSpeechProfile(1.15, 0.07, 1.20, 1.08)),
        ("restrained_anger", VoiceVoxSpeechProfile(1.08, 0.01, 1.15, 1.10)),
        ("subdued", VoiceVoxSpeechProfile(0.78, -0.02, 0.72, 0.88)),
        ("weary", VoiceVoxSpeechProfile(0.72, -0.03, 0.68, 0.82)),
    ],
)
def test_resolve_profile_uses_profile_for_each_voice_intent(
    style: str, expected_profile: VoiceVoxSpeechProfile
) -> None:
    synthesizer = create_speech_synthesizer(load_app_config())
    assert isinstance(synthesizer, VoiceVoxSpeechSynthesizer)

    profile = synthesizer._resolve_profile(VoiceIntent(style=style))

    assert profile == expected_profile
