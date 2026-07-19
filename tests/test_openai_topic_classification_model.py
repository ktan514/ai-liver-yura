from __future__ import annotations

import json
from typing import Any

import pytest

from app.adapters.topic.openai_topic_classification_model import (
    OpenAITopicClassificationConfig,
    OpenAITopicClassificationModel,
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
async def test_openai_topic_classification_model_returns_output_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(body={"output_text": "sea_life"})
    monkeypatch.setattr(
        "app.adapters.topic.openai_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OpenAITopicClassificationModel(
        OpenAITopicClassificationConfig(
            api_key="test-api-key",
            model="gpt-4.1-mini",
            base_url="https://example.com/v1",
            timeout_seconds=12.0,
        )
    )

    result = await model.classify_topic("分類してください")

    assert result == "sea_life"
    assert fake_urlopen.timeouts == [12.0]
    assert len(fake_urlopen.requests) == 1
    http_request = fake_urlopen.requests[0]
    assert http_request.full_url == "https://example.com/v1/responses"
    assert http_request.get_method() == "POST"
    assert http_request.headers["Authorization"] == "Bearer test-api-key"
    assert http_request.headers["Content-type"] == "application/json"
    body = _decode_request_body(http_request)
    assert body == {
        "model": "gpt-4.1-mini",
        "input": "分類してください",
        "temperature": 0,
    }


@pytest.mark.asyncio
async def test_openai_topic_classification_model_extracts_text_from_output_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(
        body={
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "game"},
                    ]
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.adapters.topic.openai_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OpenAITopicClassificationModel(
        OpenAITopicClassificationConfig(api_key="test-api-key", model="gpt-4.1-mini")
    )

    result = await model.classify_topic("分類してください")

    assert result == "game"


@pytest.mark.asyncio
async def test_openai_topic_classification_model_joins_multiple_output_texts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(
        body={
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "tech"},
                        {"type": "output_text", "text": "nology"},
                    ]
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.adapters.topic.openai_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OpenAITopicClassificationModel(
        OpenAITopicClassificationConfig(api_key="test-api-key", model="gpt-4.1-mini")
    )

    result = await model.classify_topic("分類してください")

    assert result == "technology"


@pytest.mark.asyncio
async def test_openai_topic_classification_model_returns_empty_string_when_response_has_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(body={"output": []})
    monkeypatch.setattr(
        "app.adapters.topic.openai_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OpenAITopicClassificationModel(
        OpenAITopicClassificationConfig(api_key="test-api-key", model="gpt-4.1-mini")
    )

    result = await model.classify_topic("分類してください")

    assert result == ""


@pytest.mark.asyncio
async def test_openai_topic_classification_model_strips_output_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_urlopen = FakeUrlOpen(body={"output_text": "\n streaming \n"})
    monkeypatch.setattr(
        "app.adapters.topic.openai_topic_classification_model.request.urlopen",
        fake_urlopen,
    )
    model = OpenAITopicClassificationModel(
        OpenAITopicClassificationConfig(api_key="test-api-key", model="gpt-4.1-mini")
    )

    result = await model.classify_topic("分類してください")

    assert result == "streaming"
