
from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import error, request

from app.common.trace import TraceLogger

from app.domain.activities import Activity
from app.domain.character import CharacterProfile
from app.runtime import PromptBuilder
from app.runtime.response_generator import ResponseGenerator


class OllamaResponseGenerator(ResponseGenerator):
    """Ollama の HTTP API を使って応答テキストを生成するアダプタ。"""

    def __init__(
        self,
        character_profile: CharacterProfile,
        prompt_builder: PromptBuilder,
        model: str,
        api_url: str = "http://localhost:11434/api/generate",
        timeout_seconds: float = 60.0,
        fallback_response: str = "うまく言葉が出てこなかったみたい。もう一度話しかけてね。",
    ) -> None:
        self._character_profile = character_profile
        self._prompt_builder = prompt_builder
        self._model = model
        self._api_url = api_url
        self._timeout_seconds = timeout_seconds
        self._fallback_response = fallback_response
        self.latest_prompt: str | None = None
        self._trace_logger = TraceLogger()

    async def generate_response(self, activity: Activity) -> str:
        self._trace_logger.write(
            "ollama_response_generator:generate_response:start",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            activity_status=activity.status.value,
            model=self._model,
            api_url=self._api_url,
            timeout_seconds=self._timeout_seconds,
        )

        self.latest_prompt = self._prompt_builder.build_prompt(
            activity=activity,
            character_profile=self._character_profile,
        )
        self._trace_logger.write(
            "ollama_response_generator:generate_response:prompt_built",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            prompt_length=len(self.latest_prompt),
        )

        payload = {
            "model": self._model,
            "prompt": self.latest_prompt,
            "stream": False,
        }

        self._trace_logger.write(
            "ollama_response_generator:generate_response:request_start",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            model=self._model,
            prompt_length=len(self.latest_prompt),
        )

        response_data = await asyncio.to_thread(self._post_generate_request, payload)
        self._trace_logger.write(
            "ollama_response_generator:generate_response:response_received",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            response_keys=list(response_data.keys()),
        )
        response_text = str(response_data.get("response", "")).strip()

        if not response_text:
            self._trace_logger.write(
                "ollama_response_generator:generate_response:fallback",
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                reason="response_text_empty",
                response_keys=list(response_data.keys()),
            )
            return self._fallback_response

        self._trace_logger.write(
            "ollama_response_generator:generate_response:success",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            response_length=len(response_text),
        )
        return response_text

    def _post_generate_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._trace_logger.write(
            "ollama_response_generator:post_generate_request:start",
            api_url=self._api_url,
            model=payload.get("model"),
            prompt_length=len(str(payload.get("prompt", ""))),
            timeout_seconds=self._timeout_seconds,
        )
        self._trace_logger.write(
            "ollama_response_generator:post_generate_request:request_building",
            payload_keys=list(payload.keys()),
        )
        request_body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self._api_url,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            self._trace_logger.write(
                "ollama_response_generator:post_generate_request:http_start",
                api_url=self._api_url,
                timeout_seconds=self._timeout_seconds,
            )
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                self._trace_logger.write(
                    "ollama_response_generator:post_generate_request:http_response_received",
                    response_length=len(response_body),
                )
        except error.URLError as exc:
            self._trace_logger.write(
                "ollama_response_generator:post_generate_request:error",
                reason="url_error",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise RuntimeError("Ollama API への接続に失敗しました。") from exc

        try:
            decoded_body = json.loads(response_body)
        except json.JSONDecodeError as exc:
            self._trace_logger.write(
                "ollama_response_generator:post_generate_request:error",
                reason="json_decode_error",
                error_type=type(exc).__name__,
                error_message=str(exc),
                response_length=len(response_body),
            )
            raise RuntimeError("Ollama API のレスポンスJSON解析に失敗しました。") from exc

        if not isinstance(decoded_body, dict):
            self._trace_logger.write(
                "ollama_response_generator:post_generate_request:error",
                reason="invalid_response_type",
                decoded_type=type(decoded_body).__name__,
            )
            raise RuntimeError("Ollama API のレスポンス形式が不正です。")

        self._trace_logger.write(
            "ollama_response_generator:post_generate_request:success",
            response_keys=list(decoded_body.keys()),
        )
        return decoded_body