from __future__ import annotations

from typing import Protocol

from app.domain.topic import TopicCategory


class TopicClassifier(Protocol):
    async def classify(self, text: str) -> TopicCategory:
        raise NotImplementedError
