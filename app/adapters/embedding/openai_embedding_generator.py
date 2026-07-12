from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib import request

from app.ports.embedding_generator import EmbeddingGenerator


@dataclass(frozen=True)
class OpenAIEmbeddingGeneratorConfig:
    api_key: str
    model: str = "text-embedding-3-small"
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 30.0


class OpenAIEmbeddingGenerator(EmbeddingGenerator):
    def __init__(self, config: OpenAIEmbeddingGeneratorConfig) -> None:
        self._config = config

    async def generate_embedding(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._generate_embedding_sync, text)

    def _generate_embedding_sync(self, text: str) -> list[float]:
        endpoint = f"{self._config.base_url.rstrip('/')}/embeddings"
        payload = {
            "model": self._config.model,
            "input": text,
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
        return self._extract_embedding(data)

    def _extract_embedding(self, data: dict[str, Any]) -> list[float]:
        data_items = data.get("data")
        if not isinstance(data_items, list) or not data_items:
            return []

        first_item = data_items[0]
        if not isinstance(first_item, dict):
            return []

        embedding = first_item.get("embedding")
        if not isinstance(embedding, list):
            return []

        return [float(value) for value in embedding]
