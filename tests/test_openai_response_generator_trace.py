from __future__ import annotations

import json
import urllib.request
from typing import Any

import pytest

from app.adapters.llm import OpenAIResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.utils.trace import TraceLogger


class _FakeHttpResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_openai_logs_actual_responses_request_and_full_result(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    debug_file = tmp_path / "runtime_debug.log"
    sent: dict[str, object] = {}

    def fake_urlopen(
        request: urllib.request.Request, timeout: float
    ) -> _FakeHttpResponse:
        sent["body"] = json.loads(request.data or b"{}")
        sent["timeout"] = timeout
        return _FakeHttpResponse({"output_text": "採用されたOpenAI返答全文"})

    monkeypatch.setenv("TEST_OPENAI_API_KEY", "sk-test-secret-value")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    TraceLogger.configure(
        level="INFO",
        trace_file_path=tmp_path / "runtime_trace.log",
        output_format="jsonl",
        debug_file_enabled=True,
        debug_file_path=debug_file,
        log_llm_prompts=True,
        log_llm_responses=True,
    )
    generator = OpenAIResponseGenerator(
        model="test-openai-model",
        api_key_env="TEST_OPENAI_API_KEY",
        timeout_seconds=3.0,
        fallback_response="fallback",
        character_profile=CharacterProfile(
            name="ミナト",
            personality="明るい",
            speaking_style="親しみやすい",
            streaming_style="雑談配信",
        ),
        prompt_builder=SimplePromptBuilder(),
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="応答する",
        source_event_id="event-1",
        context={"event_payload": {"text": "こんにちは"}},
    )
    try:
        result = await generator.generate_response(activity)

        records = [
            json.loads(line)
            for line in debug_file.read_text(encoding="utf-8").splitlines()
        ]
        request_record = next(
            record for record in records if record["label"] == "llm_request"
        )
        parsed_record = next(
            record
            for record in records
            if record["label"] == "llm_response" and record["stage"] == "parsed"
        )
        adopted_record = next(
            record
            for record in records
            if record["label"] == "llm_response" and record["stage"] == "adopted"
        )
        assert result == "採用されたOpenAI返答全文"
        assert request_record["provider"] == "openai"
        assert request_record["model"] == "test-openai-model"
        assert request_record["event_id"] == "event-1"
        assert request_record["request"] == sent["body"]
        assert "こんにちは" in request_record["request"]["input"]
        assert parsed_record["parsed_response"] == {
            "output_text": "採用されたOpenAI返答全文"
        }
        assert adopted_record["adopted_text"] == "採用されたOpenAI返答全文"
        assert "sk-test-secret-value" not in debug_file.read_text(encoding="utf-8")
    finally:
        TraceLogger.configure(
            level="INFO",
            trace_file_path=tmp_path / "restored.log",
        )
