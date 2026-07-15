

from __future__ import annotations

import json
from typing import Any

import pytest

from app.adapters.topic.ollama_topic_classification_model import (
    OllamaTopicClassificationConfig,
    OllamaTopicClassificationModel,
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
async def test_ollama_topic_classification_model_returns_response_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(body={"response": "sea_life"})
    monkeypatch.setattr(
        "app.adapters.topic.ollama_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OllamaTopicClassificationModel(
        OllamaTopicClassificationConfig(
            model="topic-classifier",
            base_url="http://localhost:11434",
            timeout_seconds=12.0,
        )
    )

    result = await model.classify_topic("分類してください")

    assert result == "sea_life"
    assert fake_urlopen.timeouts == [12.0]
    assert len(fake_urlopen.requests) == 1
    http_request = fake_urlopen.requests[0]
    assert http_request.full_url == "http://localhost:11434/api/generate"
    assert http_request.get_method() == "POST"
    assert http_request.headers["Content-type"] == "application/json"
    body = _decode_request_body(http_request)
    assert body == {
        "model": "topic-classifier",
        "prompt": "分類してください",
        "stream": False,
        "options": {
            "temperature": 0,
        },
    }


@pytest.mark.asyncio
async def test_ollama_topic_classification_model_strips_response_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(body={"response": "\n game \n"})
    monkeypatch.setattr(
        "app.adapters.topic.ollama_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OllamaTopicClassificationModel(
        OllamaTopicClassificationConfig(model="topic-classifier")
    )

    result = await model.classify_topic("分類してください")

    assert result == "game"


@pytest.mark.asyncio
async def test_ollama_topic_classification_model_returns_empty_string_when_response_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(body={})
    monkeypatch.setattr(
        "app.adapters.topic.ollama_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OllamaTopicClassificationModel(
        OllamaTopicClassificationConfig(model="topic-classifier")
    )

    result = await model.classify_topic("分類してください")

    assert result == ""


@pytest.mark.asyncio
async def test_ollama_topic_classification_model_returns_empty_string_when_response_is_not_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(body={"response": {"text": "sea_life"}})
    monkeypatch.setattr(
        "app.adapters.topic.ollama_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OllamaTopicClassificationModel(
        OllamaTopicClassificationConfig(model="topic-classifier")
    )

    result = await model.classify_topic("分類してください")

    assert result == ""


@pytest.mark.asyncio
async def test_ollama_topic_classification_model_removes_trailing_slash_from_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(body={"response": "streaming"})
    monkeypatch.setattr(
        "app.adapters.topic.ollama_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OllamaTopicClassificationModel(
        OllamaTopicClassificationConfig(
            model="topic-classifier",
            base_url="http://localhost:11434/",
        )
    )

    result = await model.classify_topic("分類してください")

    assert result == "streaming"
    assert fake_urlopen.requests[0].full_url == "http://localhost:11434/api/generate"