import json
from io import BytesIO
from urllib.error import URLError

import pytest

from app.adapters.memory.ollama_memory_summary_model import (
    OllamaMemorySummaryModel,
    OllamaMemorySummaryModelConfig,
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
async def test_generate_memory_summary_posts_prompt_to_ollama(monkeypatch) -> None:
    fake_urlopen = FakeUrlOpen(
        response_body=json.dumps(
            {"response": "イルカのジャンプの軽やかさに興味を示した"}
        )
    )
    monkeypatch.setattr(
        "app.adapters.memory.ollama_memory_summary_model.request.urlopen",
        fake_urlopen,
    )
    model = OllamaMemorySummaryModel(
        OllamaMemorySummaryModelConfig(
            base_url="http://localhost:11434/",
            model="local-memory-summary",
            timeout_seconds=12.5,
        )
    )

    summary = await model.generate_memory_summary("要約してください")

    assert summary == "イルカのジャンプの軽やかさに興味を示した"
    assert len(fake_urlopen.received_requests) == 1
    request = fake_urlopen.received_requests[0]
    assert request.full_url == "http://localhost:11434/api/generate"
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/json"
    assert fake_urlopen.received_timeouts == [12.5]
    payload = json.loads(request.data.decode("utf-8"))
    assert payload == {
        "model": "local-memory-summary",
        "prompt": "要約してください",
        "stream": False,
        "options": {"temperature": 0.2},
    }


def test_parse_response_raises_error_when_response_is_invalid_json() -> None:
    model = OllamaMemorySummaryModel(OllamaMemorySummaryModelConfig())

    with pytest.raises(RuntimeError, match="not valid json"):
        model._parse_response("not-json")


def test_parse_response_raises_error_when_response_text_is_missing() -> None:
    model = OllamaMemorySummaryModel(OllamaMemorySummaryModelConfig())

    with pytest.raises(RuntimeError, match="does not contain response text"):
        model._parse_response(json.dumps({"done": True}))


@pytest.mark.asyncio
async def test_generate_memory_summary_raises_runtime_error_when_request_fails(
    monkeypatch,
) -> None:
    def fake_urlopen(http_request, timeout: float):
        raise URLError("connection refused")

    monkeypatch.setattr(
        "app.adapters.memory.ollama_memory_summary_model.request.urlopen",
        fake_urlopen,
    )
    model = OllamaMemorySummaryModel(OllamaMemorySummaryModelConfig())

    with pytest.raises(RuntimeError, match="ollama memory summary request failed"):
        await model.generate_memory_summary("要約してください")
