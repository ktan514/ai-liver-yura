from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib import request


@dataclass(frozen=True)
class OpenAITopicClassificationConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 30.0


class OpenAITopicClassificationModel:
    def __init__(self, config: OpenAITopicClassificationConfig) -> None:
        self._config = config

    async def classify_topic(self, prompt: str) -> str:
        return await asyncio.to_thread(self._classify_topic_sync, prompt)

    def _classify_topic_sync(self, prompt: str) -> str:
        endpoint = f"{self._config.base_url.rstrip('/')}/responses"
        payload = {
            "model": self._config.model,
            "input": prompt,
            "temperature": 0,
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

        with request.urlopen(
            http_request,
            timeout=self._config.timeout_seconds,
        ) as response:
            response_body = response.read().decode("utf-8")

        data = json.loads(response_body)
        classification = self._extract_text(data)
        return classification.strip()

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
