from __future__ import annotations

from typing import Protocol

from app.domain.activities import Activity
from app.ports.response_generator import ResponseGenerator


class SituationEvaluationModel(Protocol):
    async def evaluate(self, activity: Activity) -> str: ...


class CharacterModel(Protocol):
    async def generate_character_response(self, activity: Activity) -> str: ...


class ResponseValidationModel(Protocol):
    async def validate_character_response(self, activity: Activity) -> str: ...


class ResponseGeneratorRoleAdapter:
    """既存ResponseGeneratorを明示した役割Portへ接続する移行用Adapter。"""

    def __init__(self, generator: ResponseGenerator) -> None:
        self._generator = generator

    async def evaluate(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def generate_character_response(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def validate_character_response(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def _generate(self, activity: Activity) -> str:
        result = await self._generator.generate_response(activity)
        return str(result)
