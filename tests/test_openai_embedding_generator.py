

from __future__ import annotations

import json
from typing import Any

import pytest

from app.adapters.embedding.openai_embedding_generator import (
    OpenAIEmbeddingGenerator,
    OpenAIEmbeddingGeneratorConfig,
)


class FakeHttpResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._body).encode("utf-8")


class FakeUrlOpen:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body
        self.requests: list[Any] = []
        self.timeouts: list[float] = []

    def __call__(self, http_request: Any, timeout: float) -> FakeHttpResponse:
        self.requests.append(http_request)
        self.timeouts.append(timeout)
        return FakeHttpResponse(self._body)


def _decode_request_body(http_request: Any) -> dict[str, Any]:
    data = http_request.data
    assert isinstance(data, bytes)
    return json.loads(data.decode("utf-8"))


@pytest.mark.asyncio
async def test_openai_embedding_generator_returns_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(
        body={
            "data": [
                {
                    "embedding": [0.1, 0.2, 0.3],
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.adapters.embedding.openai_embedding_generator.request.urlopen",
        fake_urlopen,
    )
    generator = OpenAIEmbeddingGenerator(
        OpenAIEmbeddingGeneratorConfig(
            api_key="test-api-key",
            model="text-embedding-3-small",
            base_url="https://example.com/v1",
            timeout_seconds=12.0,
        )
    )

    result = await generator.generate_embedding("海の色の話")

    assert result == [0.1, 0.2, 0.3]
    assert fake_urlopen.timeouts == [12.0]
    assert len(fake_urlopen.requests) == 1
    http_request = fake_urlopen.requests[0]
    assert http_request.full_url == "https://example.com/v1/embeddings"
    assert http_request.get_method() == "POST"
    assert http_request.headers["Authorization"] == "Bearer test-api-key"
    assert http_request.headers["Content-type"] == "application/json"
    body = _decode_request_body(http_request)
    assert body == {
        "model": "text-embedding-3-small",
        "input": "海の色の話",
    }


@pytest.mark.asyncio
async def test_openai_embedding_generator_converts_embedding_values_to_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(
        body={
            "data": [
                {
                    "embedding": [1, "2.5", 3.0],
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.adapters.embedding.openai_embedding_generator.request.urlopen",
        fake_urlopen,
    )
    generator = OpenAIEmbeddingGenerator(
        OpenAIEmbeddingGeneratorConfig(api_key="test-api-key")
    )

    result = await generator.generate_embedding("AIの話")

    assert result == [1.0, 2.5, 3.0]


def test_openai_embedding_generator_extracts_embedding() -> None:
    generator = OpenAIEmbeddingGenerator(
        OpenAIEmbeddingGeneratorConfig(api_key="test-api-key")
    )

    result = generator._extract_embedding(
        {
            "data": [
                {
                    "embedding": [0.1, 0.2],
                }
            ]
        }
    )

    assert result == [0.1, 0.2]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"data": []},
        {"data": ["invalid"]},
        {"data": [{}]},
        {"data": [{"embedding": "invalid"}]},
    ],
)
def test_openai_embedding_generator_returns_empty_list_when_response_has_no_embedding(
    body: dict[str, Any],
) -> None:
    generator = OpenAIEmbeddingGenerator(
        OpenAIEmbeddingGeneratorConfig(api_key="test-api-key")
    )

    result = generator._extract_embedding(body)

    assert result == []


@pytest.mark.asyncio
async def test_openai_embedding_generator_removes_trailing_slash_from_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(
        body={
            "data": [
                {
                    "embedding": [0.4, 0.5],
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.adapters.embedding.openai_embedding_generator.request.urlopen",
        fake_urlopen,
    )
    generator = OpenAIEmbeddingGenerator(
        OpenAIEmbeddingGeneratorConfig(
            api_key="test-api-key",
            base_url="https://example.com/v1/",
        )
    )

    result = await generator.generate_embedding("自然の話")

    assert result == [0.4, 0.5]
    assert fake_urlopen.requests[0].full_url == "https://example.com/v1/embeddings"