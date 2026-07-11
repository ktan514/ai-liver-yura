

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib import request


@dataclass(frozen=True)
class OllamaTopicClassificationConfig:
    model: str
    base_url: str = "http://localhost:11434"
    timeout_seconds: float = 30.0


class OllamaTopicClassificationModel:
    def __init__(self, config: OllamaTopicClassificationConfig) -> None:
        self._config = config

    async def classify_topic(self, prompt: str) -> str:
        return await asyncio.to_thread(self._classify_topic_sync, prompt)

    def _classify_topic_sync(self, prompt: str) -> str:
        endpoint = f"{self._config.base_url.rstrip('/')}/api/generate"
        payload = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with request.urlopen(
            http_request,
            timeout=self._config.timeout_seconds,
        ) as response:
            response_body = response.read().decode("utf-8")

        data = json.loads(response_body)
        classification = data.get("response", "")

        if not isinstance(classification, str):
            return ""

        return classification.strip()