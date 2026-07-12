from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from app.ports.memory_summary_model import MemorySummaryModel


@dataclass(frozen=True)
class OpenAIMemorySummaryModelConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 30.0


class OpenAIMemorySummaryModel(MemorySummaryModel):
    """OpenAI Responses API を使って長期記憶用の要約文を生成する。"""

    def __init__(self, config: OpenAIMemorySummaryModelConfig) -> None:
        self._config = config

    async def generate_memory_summary(self, prompt: str) -> str:
        return await asyncio.to_thread(self._generate_memory_summary_sync, prompt)

    def _generate_memory_summary_sync(self, prompt: str) -> str:
        endpoint = self._build_responses_endpoint()
        payload = {
            "model": self._config.model,
            "input": prompt,
            "temperature": 0.2,
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
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
                f"openai memory summary request failed: status={error.code}"
            ) from error
        except URLError as error:
            raise RuntimeError(
                f"openai memory summary request failed: reason={error.reason}"
            ) from error

        return self._parse_response(response_body)

    def _build_responses_endpoint(self) -> str:
        return f"{self._config.base_url.rstrip('/')}/responses"

    def _parse_response(self, response_body: str) -> str:
        try:
            response_json = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise RuntimeError("openai memory summary response is not valid json") from error

        summary = self._extract_text(response_json)
        if not summary:
            raise RuntimeError("openai memory summary response does not contain response text")

        return summary

    def _extract_text(self, data: dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text

        output = data.get("output")
        if not isinstance(output, list):
            return ""

        texts: list[str] = []
        for output_item in output:
            if not isinstance(output_item, dict):
                continue

            content = output_item.get("content")
            if not isinstance(content, list):
                continue

            for content_item in content:
                if not isinstance(content_item, dict):
                    continue

                text = content_item.get("text")
                if isinstance(text, str):
                    texts.append(text)

        return "".join(texts)
