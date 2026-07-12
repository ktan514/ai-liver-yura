from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from app.domain.topic import TopicCategory
from app.domain.topic_memory import SimilarTopicMemory, TopicMemoryEntry
from app.ports.topic_memory_store import TopicMemoryStore
from app.utils.trace import TraceLogger


@dataclass(frozen=True)
class PostgresTopicMemoryStoreConfig:
    dsn: str
    embedding_dimension: int


@dataclass(frozen=True)
class PostgresDatabaseErrorContext:
    operation_name: str
    phase: str
    error_type: str
    error_message: str
    dsn: str
    sql: str | None = None


class PostgresTopicMemoryStoreError(RuntimeError):
    pass


class PostgresTopicMemoryConnectionError(PostgresTopicMemoryStoreError):
    pass


class PostgresTopicMemorySqlError(PostgresTopicMemoryStoreError):
    pass


class _PostgresDatabaseClient:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._trace_logger = TraceLogger()

    async def execute(
        self,
        operation_name: str,
        sql: str,
        *args: Any,
    ) -> str:
        connection = await self._connect(operation_name)
        try:
            return str(await connection.execute(sql, *args))
        except Exception as error:
            self._log_error(
                operation_name=operation_name,
                phase="execute",
                error=error,
                sql=sql,
            )
            raise PostgresTopicMemorySqlError(
                "PostgreSQL SQL execution failed: "
                f"operation={operation_name}, "
                f"error={error.__class__.__name__}: {error}"
            ) from error
        finally:
            await self._close(connection, operation_name)

    async def fetch(
        self,
        operation_name: str,
        sql: str,
        *args: Any,
    ) -> list[Any]:
        connection = await self._connect(operation_name)
        try:
            records = await connection.fetch(sql, *args)
            return list(records)
        except Exception as error:
            self._log_error(
                operation_name=operation_name,
                phase="fetch",
                error=error,
                sql=sql,
            )
            raise PostgresTopicMemorySqlError(
                "PostgreSQL SQL fetch failed: "
                f"operation={operation_name}, "
                f"error={error.__class__.__name__}: {error}"
            ) from error
        finally:
            await self._close(connection, operation_name)

    async def _connect(self, operation_name: str) -> Any:
        try:
            return await asyncpg.connect(self._dsn)
        except Exception as error:
            self._log_error(
                operation_name=operation_name,
                phase="connect",
                error=error,
                sql=None,
            )
            raise PostgresTopicMemoryConnectionError(
                "PostgreSQL connection failed: "
                f"operation={operation_name}, "
                f"error={error.__class__.__name__}: {error}"
            ) from error

    async def _close(self, connection: Any, operation_name: str) -> None:
        try:
            await connection.close()
        except Exception as error:
            self._log_error(
                operation_name=operation_name,
                phase="close",
                error=error,
                sql=None,
            )

    def _log_error(
        self,
        operation_name: str,
        phase: str,
        error: Exception,
        sql: str | None,
    ) -> None:
        context = PostgresDatabaseErrorContext(
            operation_name=operation_name,
            phase=phase,
            error_type=error.__class__.__name__,
            error_message=str(error),
            dsn=self._mask_dsn(self._dsn),
            sql=self._format_sql_for_log(sql) if sql is not None else None,
        )
        self._trace_logger.write(
            "postgres_topic_memory_store:database_error",
            operation=context.operation_name,
            phase=context.phase,
            error_type=context.error_type,
            error_message=context.error_message,
            dsn=context.dsn,
            sql=context.sql,
        )

    @staticmethod
    def _mask_dsn(dsn: str) -> str:
        if "://" not in dsn or "@" not in dsn:
            return dsn

        scheme, rest = dsn.split("://", 1)
        credentials, host_part = rest.split("@", 1)
        if ":" not in credentials:
            return f"{scheme}://{credentials}@{host_part}"

        user, _password = credentials.split(":", 1)
        return f"{scheme}://{user}:***@{host_part}"

    @staticmethod
    def _format_sql_for_log(sql: str) -> str:
        return " ".join(sql.split())


class PostgresTopicMemoryStore(TopicMemoryStore):
    def __init__(self, config: PostgresTopicMemoryStoreConfig) -> None:
        self._config = config
        self._database_client = _PostgresDatabaseClient(config.dsn)

    async def initialize(self) -> None:
        await self._database_client.execute(
            "initialize:create_extension",
            "CREATE EXTENSION IF NOT EXISTS vector",
        )
        await self._database_client.execute(
            "initialize:create_table",
            f"""
                CREATE TABLE IF NOT EXISTS topic_memories (
                    id BIGSERIAL PRIMARY KEY,
                    category TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    source_activity_id TEXT,
                    embedding vector({self._config.embedding_dimension}) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """,
        )
        await self._database_client.execute(
            "initialize:create_created_at_index",
            """
                CREATE INDEX IF NOT EXISTS idx_topic_memories_created_at
                ON topic_memories (created_at DESC)
                """,
        )
        await self._database_client.execute(
            "initialize:create_category_index",
            """
                CREATE INDEX IF NOT EXISTS idx_topic_memories_category
                ON topic_memories (category)
                """,
        )
        await self._database_client.execute(
            "initialize:create_embedding_index",
            """
                CREATE INDEX IF NOT EXISTS idx_topic_memories_embedding_hnsw
                ON topic_memories
                USING hnsw (embedding vector_cosine_ops)
                """,
        )

    async def save(self, entry: TopicMemoryEntry) -> None:
        self._validate_embedding_dimension(entry.embedding)

        await self._database_client.execute(
            "save",
            """
                INSERT INTO topic_memories (
                    category,
                    summary,
                    source_text,
                    activity_type,
                    source_activity_id,
                    embedding,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6::vector, $7)
                """,
            entry.category.value,
            entry.summary,
            entry.source_text,
            entry.activity_type,
            entry.source_activity_id,
            self._format_vector(entry.embedding),
            self._ensure_timezone(entry.created_at),
        )

    async def fetch_recent(self, limit: int = 10) -> list[TopicMemoryEntry]:
        records = await self._database_client.fetch(
            "fetch_recent",
            """
                SELECT
                    category,
                    summary,
                    source_text,
                    activity_type,
                    source_activity_id,
                    embedding::text AS embedding,
                    created_at
                FROM topic_memories
                ORDER BY created_at DESC, id DESC
                LIMIT $1
                """,
            limit,
        )
        return [self._record_to_entry(record) for record in records]

    async def search_similar(
        self,
        embedding: list[float],
        limit: int = 5,
    ) -> list[SimilarTopicMemory]:
        self._validate_embedding_dimension(embedding)

        records = await self._database_client.fetch(
            "search_similar",
            """
                SELECT
                    category,
                    summary,
                    source_text,
                    activity_type,
                    source_activity_id,
                    embedding::text AS embedding,
                    created_at,
                    1 - (embedding <=> $1::vector) AS similarity
                FROM topic_memories
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
            self._format_vector(embedding),
            limit,
        )
        return [
            SimilarTopicMemory(
                entry=self._record_to_entry(record),
                similarity=float(record["similarity"]),
            )
            for record in records
        ]

    def _validate_embedding_dimension(self, embedding: list[float]) -> None:
        if len(embedding) != self._config.embedding_dimension:
            raise ValueError(
                "embedding dimension mismatch: "
                f"expected {self._config.embedding_dimension}, got {len(embedding)}"
            )

    def _format_vector(self, embedding: list[float]) -> str:
        return "[" + ",".join(str(value) for value in embedding) + "]"

    def _parse_vector(self, value: str) -> list[float]:
        stripped_value = value.strip()
        if not stripped_value.startswith("[") or not stripped_value.endswith("]"):
            raise ValueError(f"invalid vector format: {value}")

        content = stripped_value[1:-1].strip()
        if not content:
            return []

        return [float(item) for item in content.split(",")]

    def _record_to_entry(self, record: Any) -> TopicMemoryEntry:
        return TopicMemoryEntry(
            category=TopicCategory(record["category"]),
            summary=record["summary"],
            source_text=record["source_text"],
            activity_type=record["activity_type"],
            source_activity_id=record["source_activity_id"],
            embedding=self._parse_vector(record["embedding"]),
            created_at=self._ensure_timezone(record["created_at"]),
        )

    def _ensure_timezone(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
