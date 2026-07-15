from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib import request
from urllib.error import HTTPError, URLError

from app.ports.memory_summary_model import MemorySummaryModel


@dataclass(frozen=True)
class OllamaMemorySummaryModelConfig:
    base_url: str = "http://localhost:11434"
    model: str = "llama3.1"
    timeout_seconds: float = 30.0


class OllamaMemorySummaryModel(MemorySummaryModel):
    """Ollama の generate API を使って長期記憶用の要約文を生成する。"""

    def __init__(self, config: OllamaMemorySummaryModelConfig) -> None:
        self._config = config

    async def generate_memory_summary(self, prompt: str) -> str:
        return await asyncio.to_thread(self._generate_memory_summary_sync, prompt)

    def _generate_memory_summary_sync(self, prompt: str) -> str:
        endpoint = self._build_generate_endpoint()
        payload = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self._config.timeout_seconds,
            ) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as error:
            raise RuntimeError(
                f"ollama memory summary request failed: status={error.code}"
            ) from error
        except URLError as error:
            raise RuntimeError(
                f"ollama memory summary request failed: reason={error.reason}"
            ) from error

        return self._parse_response(response_body)

    def _build_generate_endpoint(self) -> str:
        return self._config.base_url.rstrip("/") + "/api/generate"

    def _parse_response(self, response_body: str) -> str:
        try:
            response_json = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise RuntimeError("ollama memory summary response is not valid json") from error

        summary = response_json.get("response")
        if not isinstance(summary, str):
            raise RuntimeError("ollama memory summary response does not contain response text")

        return summary
