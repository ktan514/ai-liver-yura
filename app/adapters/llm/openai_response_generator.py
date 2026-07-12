from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

from app.adapters.prompt import SimplePromptBuilder
from app.domain.activities import Activity
from app.domain.character import CharacterProfile
from app.utils.trace import TraceLogger


class OpenAIResponseGenerator:
    """OpenAI Responses API を使う ResponseGenerator Adapter。"""

    def __init__(
        self,
        model: str,
        api_key_env: str,
        timeout_seconds: float,
        fallback_response: str,
        character_profile: CharacterProfile,
        prompt_builder: SimplePromptBuilder,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._model = model
        self._api_key_env = api_key_env
        self._timeout_seconds = timeout_seconds
        self._fallback_response = fallback_response
        self._character_profile = character_profile
        self._prompt_builder = prompt_builder
        self._base_url = base_url
        self._trace_logger = TraceLogger()

    async def generate_response(self, activity: Activity) -> str:
        self._trace_logger.write(
            "openai_response_generator:generate_response:start",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            activity_status=activity.status.value,
        )
        prompt = self._prompt_builder.build_prompt(
            character_profile=self._character_profile,
            activity=activity,
        )
        self._trace_logger.write(
            "openai_response_generator:generate_response:prompt_built",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            prompt_length=len(prompt),
        )
        response_text = await asyncio.to_thread(self._generate_sync, prompt)
        self._trace_logger.write(
            "openai_response_generator:generate_response:finished",
            level="DEBUG" if response_text == self._fallback_response else "INFO",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            response_length=len(response_text),
            fallback_used=response_text == self._fallback_response,
        )
        return response_text

    async def generate(self, prompt: str) -> str:
        self._trace_logger.write(
            "openai_response_generator:generate:start",
            prompt_length=len(prompt),
        )
        response_text = await asyncio.to_thread(self._generate_sync, prompt)
        self._trace_logger.write(
            "openai_response_generator:generate:finished",
            response_length=len(response_text),
            fallback_used=response_text == self._fallback_response,
        )
        return response_text

    def _generate_sync(self, prompt: str) -> str:
        self._trace_logger.write(
            "openai_response_generator:generate_sync:start",
            model=self._model,
            api_key_env=self._api_key_env,
            prompt_length=len(prompt),
            timeout_seconds=self._timeout_seconds,
        )
        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            self._trace_logger.write(
                "openai_response_generator:generate_sync:fallback",
                reason="api_key_missing",
                api_key_env=self._api_key_env,
            )
            return self._fallback_response

        self._trace_logger.write(
            "openai_response_generator:generate_sync:request_building",
            model=self._model,
            prompt_length=len(prompt),
        )
        request_body = json.dumps(
            {
                "model": self._model,
                "input": prompt,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self._base_url.rstrip('/')}/responses",
            data=request_body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            self._trace_logger.write(
                "openai_response_generator:generate_sync:request_start",
                model=self._model,
                timeout_seconds=self._timeout_seconds,
            )
            with urllib.request.urlopen(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                response_body = response.read().decode("utf-8")
                self._trace_logger.write(
                    "openai_response_generator:generate_sync:response_received",
                    response_length=len(response_body),
                )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            self._trace_logger.write(
                "openai_response_generator:generate_sync:fallback",
                reason="request_failed",
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return self._fallback_response

        try:
            response_json = json.loads(response_body)
        except json.JSONDecodeError as error:
            self._trace_logger.write(
                "openai_response_generator:generate_sync:fallback",
                reason="response_json_decode_failed",
                error_type=type(error).__name__,
                error_message=str(error),
                response_length=len(response_body),
            )
            return self._fallback_response

        generated_text = self._extract_output_text(response_json)
        if not generated_text:
            self._trace_logger.write(
                "openai_response_generator:generate_sync:fallback",
                reason="generated_text_empty",
                response_keys=list(response_json.keys()),
            )
            return self._fallback_response

        self._trace_logger.info(
            "openai_response_generator:generate_sync:success",
            generated_text_length=len(generated_text.strip()),
        )
        return generated_text.strip()

    def _extract_output_text(self, response_json: dict[str, Any]) -> str:
        output_text = response_json.get("output_text")
        if isinstance(output_text, str):
            return output_text

        output = response_json.get("output")
        if not isinstance(output, list):
            return ""

        text_parts: list[str] = []
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
                    text_parts.append(text)

        return "".join(text_parts)
