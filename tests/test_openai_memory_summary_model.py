from __future__ import annotations

import json
from io import BytesIO
from urllib.error import URLError

import pytest

from app.adapters.memory.openai_memory_summary_model import (
    OpenAIMemorySummaryModel,
    OpenAIMemorySummaryModelConfig,
)


class FakeHttpResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return BytesIO(self._body).read()


class FakeUrlOpen:
    def __init__(self, response_body: str) -> None:
        self.response_body = response_body
        self.received_requests = []
        self.received_timeouts: list[float] = []

    def __call__(self, http_request, timeout: float):
        self.received_requests.append(http_request)
        self.received_timeouts.append(timeout)
        return FakeHttpResponse(self.response_body)


@pytest.mark.asyncio
async def test_generate_memory_summary_posts_prompt_to_openai(monkeypatch) -> None:
    fake_urlopen = FakeUrlOpen(
        response_body=json.dumps({"output_text": "イルカのジャンプの軽やかさに興味を示した"})
    )
    monkeypatch.setattr(
        "app.adapters.memory.openai_memory_summary_model.request.urlopen",
        fake_urlopen,
    )
    model = OpenAIMemorySummaryModel(
        OpenAIMemorySummaryModelConfig(
            api_key="test-api-key",
            base_url="https://example.com/v1/",
            model="gpt-4.1-mini",
            timeout_seconds=12.5,
        )
    )

    summary = await model.generate_memory_summary("要約してください")

    assert summary == "イルカのジャンプの軽やかさに興味を示した"
    assert len(fake_urlopen.received_requests) == 1
    request = fake_urlopen.received_requests[0]
    assert request.full_url == "https://example.com/v1/responses"
    assert request.get_method() == "POST"
    assert request.headers["Authorization"] == "Bearer test-api-key"
    assert request.headers["Content-type"] == "application/json"
    assert fake_urlopen.received_timeouts == [12.5]
    payload = json.loads(request.data.decode("utf-8"))
    assert payload == {
        "model": "gpt-4.1-mini",
        "input": "要約してください",
        "temperature": 0.2,
    }


def test_parse_response_extracts_text_from_output_content() -> None:
    model = OpenAIMemorySummaryModel(
        OpenAIMemorySummaryModelConfig(api_key="test-api-key", model="gpt-4.1-mini")
    )

    summary = model._parse_response(
        json.dumps(
            {
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": "イルカの"},
                            {"type": "output_text", "text": "話を覚えた"},
                        ]
                    }
                ]
            }
        )
    )

    assert summary == "イルカの話を覚えた"


def test_parse_response_raises_error_when_response_is_invalid_json() -> None:
    model = OpenAIMemorySummaryModel(
        OpenAIMemorySummaryModelConfig(api_key="test-api-key", model="gpt-4.1-mini")
    )

    with pytest.raises(RuntimeError, match="not valid json"):
        model._parse_response("not-json")


def test_parse_response_raises_error_when_response_text_is_missing() -> None:
    model = OpenAIMemorySummaryModel(
        OpenAIMemorySummaryModelConfig(api_key="test-api-key", model="gpt-4.1-mini")
    )

    with pytest.raises(RuntimeError, match="does not contain response text"):
        model._parse_response(json.dumps({"output": []}))


@pytest.mark.asyncio
async def test_generate_memory_summary_raises_runtime_error_when_request_fails(monkeypatch) -> None:
    def fake_urlopen(http_request, timeout: float):
        raise URLError("connection refused")

    monkeypatch.setattr(
        "app.adapters.memory.openai_memory_summary_model.request.urlopen",
        fake_urlopen,
    )
    model = OpenAIMemorySummaryModel(
        OpenAIMemorySummaryModelConfig(api_key="test-api-key", model="gpt-4.1-mini")
    )

    with pytest.raises(RuntimeError, match="openai memory summary request failed"):
        await model.generate_memory_summary("要約してください")
