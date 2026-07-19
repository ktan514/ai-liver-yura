from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.adapters.storage.postgres_topic_memory_store import (  # noqa: E402
    PostgresTopicMemoryStore,
    PostgresTopicMemoryStoreConfig,
)
from app.config.app_config import load_app_config  # noqa: E402


async def main() -> None:
    config = load_app_config()
    topic_memory_config = config.memory.topic_memory

    if not topic_memory_config.enabled:
        print(
            "topic_memory is disabled. Set memory.topic_memory.enabled=true to initialize DB."
        )
        return

    if topic_memory_config.database.type != "postgres":
        raise RuntimeError(
            "unsupported topic memory database type: "
            f"{topic_memory_config.database.type}"
        )

    dsn = os.environ.get(topic_memory_config.database.dsn_env, "")
    if not dsn:
        raise RuntimeError(
            "database dsn is not set: " f"{topic_memory_config.database.dsn_env}"
        )

    store = PostgresTopicMemoryStore(
        PostgresTopicMemoryStoreConfig(
            dsn=dsn,
            embedding_dimension=topic_memory_config.embedding.dimension,
        )
    )
    await store.initialize()
    print("topic memory database initialized.")


if __name__ == "__main__":
    asyncio.run(main())
