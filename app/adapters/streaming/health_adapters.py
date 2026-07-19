from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from uuid import uuid4

from app.plugins.youtube_streaming.domain import HealthCheckItem, HealthStatus


@dataclass(frozen=True, slots=True)
class VoiceVoxHealthConfig:
    base_url: str
    timeout_seconds: float
    speaker_id: int
    player_command: str


class VoiceVoxHealthAdapter:
    def __init__(self, config: VoiceVoxHealthConfig) -> None:
        self._config = config

    async def check(self, *, required: bool) -> HealthCheckItem:
        started = time.perf_counter()
        try:
            version, speakers = await asyncio.wait_for(
                asyncio.gather(
                    asyncio.to_thread(self._get_json, "/version"),
                    asyncio.to_thread(self._get_json, "/speakers"),
                ),
                timeout=self._config.timeout_seconds,
            )
            if not isinstance(speakers, list):
                raise RuntimeError("VOICEVOX speakers応答がlistではありません。")
            styles = [
                style.get("id")
                for speaker in speakers
                if isinstance(speaker, dict)
                for style in speaker.get("styles", [])
                if isinstance(style, dict)
            ]
            if self._config.speaker_id not in styles:
                raise RuntimeError(
                    f"VOICEVOX speaker/style {self._config.speaker_id} は利用できません。"
                )
            command = shlex.split(self._config.player_command)[0]
            if shutil.which(command) is None:
                raise RuntimeError(f"音声再生Commandが見つかりません: {command}")
            return self._item(
                required,
                HealthStatus.HEALTHY,
                f"VOICEVOX {version} を利用できます。",
                started,
                metadata={"version": version, "speaker_id": self._config.speaker_id},
            )
        except (asyncio.TimeoutError, TimeoutError) as error:
            return self._item(
                required,
                HealthStatus.UNAVAILABLE,
                "VOICEVOX Health Checkがtimeoutしました。",
                started,
                failure_reason=str(error) or "VOICEVOX timeout",
                retryable=True,
            )
        except Exception as error:
            return self._item(
                required,
                HealthStatus.UNAVAILABLE,
                "VOICEVOXを利用できません。",
                started,
                failure_reason=str(error),
                retryable=True,
            )

    def _get_json(self, path: str) -> object:
        request = urllib.request.Request(
            f"{self._config.base_url.rstrip('/')}{path}", method="GET"
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 -- configured local service
                request, timeout=self._config.timeout_seconds
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise RuntimeError(f"VOICEVOX {path} の確認に失敗しました。") from error

    @staticmethod
    def _item(
        required: bool,
        status: HealthStatus,
        summary: str,
        started: float,
        *,
        failure_reason: str | None = None,
        retryable: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> HealthCheckItem:
        return HealthCheckItem(
            check_id=f"tts-{uuid4()}",
            component="tts.available",
            status=status,
            required=required,
            summary=summary,
            failure_reason=failure_reason,
            latency_ms=(time.perf_counter() - started) * 1000,
            retryable=retryable,
            metadata=metadata or {},
        )


@dataclass(frozen=True, slots=True)
class FakeAvatarHealthAdapter:
    status: HealthStatus = HealthStatus.HEALTHY
    failure_reason: str | None = None

    async def check(self, *, required: bool) -> HealthCheckItem:
        return HealthCheckItem(
            check_id=f"avatar-{uuid4()}",
            component="avatar.available",
            status=self.status,
            required=required,
            summary=(
                "Avatarを利用できます。"
                if self.status == HealthStatus.HEALTHY
                else "Avatar連携は利用できません。"
            ),
            failure_reason=self.failure_reason,
            retryable=self.status != HealthStatus.HEALTHY,
        )


class UnavailableAvatarHealthAdapter(FakeAvatarHealthAdapter):
    def __init__(self) -> None:
        super().__init__(
            status=HealthStatus.DEGRADED,
            failure_reason="実Avatar連携は未実装です。",
        )


class FakeTtsHealthAdapter:
    async def check(self, *, required: bool) -> HealthCheckItem:
        return HealthCheckItem(
            check_id=f"tts-{uuid4()}",
            component="tts.available",
            status=HealthStatus.HEALTHY,
            required=required,
            summary="Demo TTSを利用できます（音声は再生しません）。",
            metadata={"adapter_type": "fake"},
        )
