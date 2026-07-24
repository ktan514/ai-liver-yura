from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.adapters.storage.postgres_topic_memory_store import (
    PostgresTopicMemoryStore,
    PostgresTopicMemoryStoreConfig,
)
from app.domain.topic_memory import TopicMemoryEntry
from app.domain.topic import TopicCategory
from app.config.app_config import load_app_config


async def main() -> None:
    config = load_app_config()
    topic_memory_config = config.memory.topic_memory

    if not topic_memory_config.enabled:
        print("topic_memory is disabled in config. Enable it to run this script.")
        return

    # Resolve database DSN from the configured service reference
    service_name = topic_memory_config.database_service
    service = config.services.get(service_name)
    if service is None or service.dsn_env is None:
        raise RuntimeError(f"missing services.{service_name}.dsn_env in config")

    dsn = os.environ.get(service.dsn_env, "")
    if not dsn:
        raise RuntimeError("database dsn is not set: " f"{service.dsn_env}")

    # Resolve embedding dimension from the configured embedding model
    embedding_model_key = topic_memory_config.embedding_model
    model = config.models.get(embedding_model_key)
    if model is None or model.dimension is None:
        raise RuntimeError(f"missing models.{embedding_model_key}.dimension in config")

    store = PostgresTopicMemoryStore(
        PostgresTopicMemoryStoreConfig(dsn=dsn, embedding_dimension=model.dimension)
    )

    # create a sample embedding vector with the configured dimension
    dim = model.dimension
    sample_embedding = [0.01] * dim

    entry = TopicMemoryEntry(
        category=TopicCategory.NATURE,
        summary="テスト: サンプルのトピック記憶",
        source_text="これはテスト目的で保存されたトピック記憶です。",
        activity_type="speak",
        embedding=sample_embedding,
        source_activity_id="sample-1",
        created_at=datetime.now(timezone.utc),
    )

    await store.save(entry)
    print("saved sample topic memory")

    recent = await store.fetch_recent(limit=5)
    print(f"recent count: {len(recent)}")
    for r in recent:
        print(f"- {r.created_at.isoformat()} {r.category} {r.summary}")


if __name__ == "__main__":
    asyncio.run(main())
