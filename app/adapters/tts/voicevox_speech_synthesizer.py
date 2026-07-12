from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from app.adapters.tts.audio_query_corrector import AudioQueryCorrector, NoOpAudioQueryCorrector
from app.adapters.tts.pronunciation_corrector import PronunciationCorrector
from app.domain.emotions import EmotionState
from app.ports.speech_synthesizer import SpeechSynthesizer
from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class VoiceVoxSpeechProfile:
    speed_scale: float
    pitch_scale: float
    intonation_scale: float
    volume_scale: float


@dataclass(frozen=True, slots=True)
class VoiceVoxSpeechSynthesizerConfig:
    base_url: str
    speaker_id: int
    timeout_seconds: float = 30.0
    default_profile: str = "neutral"
    emotion_profiles: dict[str, VoiceVoxSpeechProfile] | None = None


class VoiceVoxSpeechSynthesizer(SpeechSynthesizer):
    """VOICEVOX ENGINE APIを使ってWAV音声を生成する。"""

    def __init__(
        self,
        config: VoiceVoxSpeechSynthesizerConfig,
        pronunciation_corrector: PronunciationCorrector | None = None,
        audio_query_corrector: AudioQueryCorrector | None = None,
    ) -> None:
        self._config = config
        self._pronunciation_corrector = pronunciation_corrector
        self._audio_query_corrector = audio_query_corrector or NoOpAudioQueryCorrector()
        self._trace_logger = TraceLogger()

    async def synthesize(self, text: str, emotion: EmotionState | None = None) -> bytes:
        if not text.strip():
            raise ValueError("音声合成するテキストが空です。")
        profile = self._resolve_profile(emotion)
        return await asyncio.to_thread(self._synthesize_sync, text, profile)

    def _synthesize_sync(self, text: str, profile: VoiceVoxSpeechProfile) -> bytes:
        corrected_text = self._correct_pronunciation(text)
        audio_query = self._create_audio_query(corrected_text)
        audio_query.update(
            {
                "speedScale": profile.speed_scale,
                "pitchScale": profile.pitch_scale,
                "intonationScale": profile.intonation_scale,
                "volumeScale": profile.volume_scale,
            }
        )
        safe_audio_query = copy.deepcopy(audio_query)
        try:
            corrected_audio_query = self._audio_query_corrector.correct(
                original_text=text,
                corrected_text=corrected_text,
                audio_query=copy.deepcopy(audio_query),
            )
        except Exception as error:
            self._trace_logger.warning(
                "voicevox_speech_synthesizer:audio_query_correction:failed",
                error_type=type(error).__name__,
                error_message=str(error),
            )
            corrected_audio_query = safe_audio_query
        return self._request_synthesis(corrected_audio_query)

    def _correct_pronunciation(self, text: str) -> str:
        if self._pronunciation_corrector is None:
            return text
        try:
            result = self._pronunciation_corrector.correct(text)
        except Exception as error:
            self._trace_logger.warning(
                "voicevox_speech_synthesizer:pronunciation_correction:failed",
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return text
        if result.applied_rules:
            self._trace_logger.info(
                "voicevox_speech_synthesizer:pronunciation_corrected",
                original=self._abbreviate(result.original_text),
                corrected=self._abbreviate(result.corrected_text),
                rules=len(result.applied_rules),
            )
        return result.corrected_text

    @staticmethod
    def _abbreviate(text: str, max_length: int = 80) -> str:
        return text if len(text) <= max_length else f"{text[:max_length]}…"

    def _resolve_profile(self, emotion: EmotionState | None) -> VoiceVoxSpeechProfile:
        profiles = self._config.emotion_profiles or {
            "neutral": VoiceVoxSpeechProfile(1.0, 0.0, 1.0, 1.0)
        }
        profile_name = emotion.mood.value if emotion is not None else self._config.default_profile
        return profiles.get(profile_name, profiles[self._config.default_profile])

    def _create_audio_query(self, text: str) -> dict[str, Any]:
        query = parse.urlencode({"text": text, "speaker": self._config.speaker_id})
        response_body = self._post(f"/audio_query?{query}", body=b"")
        try:
            data = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("VOICEVOXの音声クエリ応答を解析できません。") from exc
        if not isinstance(data, dict):
            raise RuntimeError("VOICEVOXの音声クエリ応答形式が不正です。")
        return data

    def _request_synthesis(self, audio_query: dict[str, Any]) -> bytes:
        query = parse.urlencode({"speaker": self._config.speaker_id})
        body = json.dumps(audio_query, ensure_ascii=False).encode("utf-8")
        audio_data = self._post(
            f"/synthesis?{query}",
            body=body,
            content_type="application/json",
        )
        if not audio_data:
            raise RuntimeError("VOICEVOXから空の音声データが返されました。")
        return audio_data

    def _post(
        self,
        path: str,
        *,
        body: bytes,
        content_type: str = "application/octet-stream",
    ) -> bytes:
        endpoint = f"{self._config.base_url.rstrip('/')}{path}"
        http_request = request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self._config.timeout_seconds) as response:
                response_body = response.read()
                if not isinstance(response_body, bytes):
                    raise RuntimeError("VOICEVOX APIの応答形式が不正です。")
                return response_body
        except error.HTTPError as exc:
            raise RuntimeError(f"VOICEVOX APIエラー: status={exc.code}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise RuntimeError("VOICEVOX ENGINEへ接続できません。") from exc
