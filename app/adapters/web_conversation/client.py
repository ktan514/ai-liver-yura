from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib.request import Request, urlopen

from app.ports.audio_player import AudioPlayer
from app.ports.conversation_output import ConversationOutputPublisher


@dataclass(frozen=True)
class WebConversationClientConfig:
    base_url: str = "http://127.0.0.1:8770"
    connect_timeout_seconds: float = 2.0
    playback_timeout_seconds: float = 180.0


class WebConversationClient(AudioPlayer, ConversationOutputPublisher):
    """会話出力とWAV再生を独立Web画面へ委譲するクライアント。"""

    def __init__(self, config: WebConversationClientConfig | None = None) -> None:
        self._config = config or WebConversationClientConfig()
        self._base_url = self._config.base_url.rstrip("/")

    async def publish_text(self, *, kind: str, text: str, action_id: str) -> None:
        payload = json.dumps(
            {"schema_version": 1, "kind": kind, "text": text, "action_id": action_id},
            ensure_ascii=False,
        ).encode("utf-8")
        await asyncio.to_thread(
            self._post,
            "/api/output",
            payload,
            "application/json; charset=utf-8",
            self._config.connect_timeout_seconds,
        )

    async def play(self, audio_data: bytes) -> None:
        if not audio_data:
            raise ValueError("Web画面へ送る音声データが空です。")
        response = await asyncio.to_thread(
            self._post,
            "/api/audio",
            audio_data,
            "audio/wav",
            self._config.playback_timeout_seconds,
        )
        result = json.loads(response.decode("utf-8"))
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise RuntimeError("Web画面で音声再生が完了しませんでした。")

    def _post(
        self,
        path: str,
        body: bytes,
        content_type: str,
        timeout: float,
    ) -> bytes:
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return bytes(response.read())
