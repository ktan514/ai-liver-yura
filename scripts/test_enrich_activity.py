from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.usecases.enrich_activity_with_topic_memory_usecase import (
    EnrichActivityWithTopicMemoryUsecase,
)
from app.adapters.storage.postgres_topic_memory_store import (
    PostgresTopicMemoryStore,
    PostgresTopicMemoryStoreConfig,
)
from app.domain.activities.activity import Activity
from app.domain.activities.activity_type import ActivityType
from app.config.app_config import load_app_config


class FakeEmbeddingGenerator:
    async def generate_embedding(self, text: str) -> List[float]:
        # Return an embedding that matches the sample inserted earlier
        config = load_app_config()
        dim = config.models[config.memory.topic_memory.embedding_model].dimension
        return [0.01] * dim


async def main() -> None:
    config = load_app_config()
    topic_memory_config = config.memory.topic_memory

    dsn = os.environ.get("AI_LIVER_DATABASE_URL")
    if not dsn:
        service_name = topic_memory_config.database_service
        service = config.services.get(service_name)
        dsn = os.environ.get(service.dsn_env, "")
    if not dsn:
        raise RuntimeError("AI_LIVER_DATABASE_URL not set")

    model = config.models[topic_memory_config.embedding_model]
    store = PostgresTopicMemoryStore(
        PostgresTopicMemoryStoreConfig(dsn=dsn, embedding_dimension=model.dimension)
    )

    embedding_generator = FakeEmbeddingGenerator()
    usecase = EnrichActivityWithTopicMemoryUsecase(
        embedding_generator=embedding_generator, topic_memory_store=store, search_limit=5
    )

    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="",
        context={"event_payload": {"text": "テスト用のクエリ"}},
    )

    enriched = await usecase.enrich(activity)

    similar = enriched.context.get("similar_topic_memories") or []
    print(f"found {len(similar)} similar topic memories")
    for mem in similar:
        entry = mem.entry
        print(f"- {mem.similarity:.3f} {entry.category} {entry.summary}")


if __name__ == "__main__":
    asyncio.run(main())
