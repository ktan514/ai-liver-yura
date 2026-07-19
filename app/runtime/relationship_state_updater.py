from __future__ import annotations

from app.domain.events import AgentEvent, AgentEventType
from app.domain.relationships import (
    RelationshipIdentity,
    RelationshipMemory,
    RelationshipState,
)


class RelationshipStateUpdater:
    """Eventの安定した相手識別情報からRelationshipMemoryを更新する。"""

    _local_input_types = {AgentEventType.USER_TEXT, AgentEventType.USER_SPEECH}

    def preview(
        self,
        memory: RelationshipMemory,
        event: AgentEvent,
    ) -> RelationshipState | None:
        identity = self.identity(event)
        if identity is None:
            return None
        return memory.record(
            identity,
            event_id=event.event_id,
            occurred_at=event.occurred_at,
        ).current

    def update(
        self, memory: RelationshipMemory, event: AgentEvent
    ) -> RelationshipMemory:
        identity = self.identity(event)
        if identity is None:
            return memory
        return memory.record(
            identity,
            event_id=event.event_id,
            occurred_at=event.occurred_at,
        )

    def identity(self, event: AgentEvent) -> RelationshipIdentity | None:
        explicit_id = event.payload.get("counterpart_id")
        if isinstance(explicit_id, str) and explicit_id.strip():
            return RelationshipIdentity(
                counterpart_id=explicit_id.strip(),
                display_name=self._text(
                    event.payload.get("counterpart_name"), "ユーザー"
                ),
                role=self._text(event.payload.get("counterpart_role"), "user"),
            )

        author = event.payload.get("author")
        if isinstance(author, dict):
            channel_id = author.get("channel_id")
            if isinstance(channel_id, str) and channel_id.strip():
                return RelationshipIdentity(
                    counterpart_id=f"youtube:{channel_id.strip()}",
                    display_name=self._text(author.get("display_name"), "視聴者"),
                    role=self._text(author.get("role"), "viewer"),
                )

        target = event.payload.get("comment_response_target")
        if isinstance(target, dict):
            author_id = target.get("author_id")
            if isinstance(author_id, str) and author_id.strip():
                return RelationshipIdentity(
                    counterpart_id=f"youtube:{author_id.strip()}",
                    display_name="視聴者",
                    role="viewer",
                )

        if event.event_type in self._local_input_types:
            source = self._text(event.payload.get("source"), "local")
            return RelationshipIdentity(
                counterpart_id="local:user",
                display_name=self._text(event.payload.get("user_name"), "ユーザー"),
                role=source,
            )
        return None

    @staticmethod
    def _text(value: object, default: str) -> str:
        return value.strip() if isinstance(value, str) and value.strip() else default
