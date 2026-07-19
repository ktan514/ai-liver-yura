from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class RelationshipIdentity:
    counterpart_id: str
    display_name: str
    role: str = "user"

    def __post_init__(self) -> None:
        if not self.counterpart_id.strip():
            raise ValueError("counterpart_idは空にできません。")
        if not self.display_name.strip():
            raise ValueError("display_nameは空にできません。")


@dataclass(frozen=True, slots=True)
class RelationshipState:
    """特定の相手との、発話内容から独立して保持する継続関係状態。"""

    counterpart_id: str
    display_name: str
    role: str = "user"
    familiarity: float = 0.0
    trust: float = 0.5
    affinity: float = 0.0
    interaction_count: int = 0
    last_interaction_at: datetime | None = None
    last_event_id: str | None = None

    def __post_init__(self) -> None:
        if not self.counterpart_id.strip():
            raise ValueError("counterpart_idは空にできません。")
        if not self.display_name.strip():
            raise ValueError("display_nameは空にできません。")
        self._validate_range("familiarity", self.familiarity, 0.0, 1.0)
        self._validate_range("trust", self.trust, 0.0, 1.0)
        self._validate_range("affinity", self.affinity, -1.0, 1.0)
        if self.interaction_count < 0:
            raise ValueError("interaction_countは0以上にしてください。")

    def record_interaction(
        self,
        identity: RelationshipIdentity,
        *,
        event_id: str,
        occurred_at: datetime,
    ) -> RelationshipState:
        if identity.counterpart_id != self.counterpart_id:
            raise ValueError("異なる相手のinteractionは記録できません。")
        if event_id == self.last_event_id:
            return self
        return replace(
            self,
            display_name=identity.display_name,
            role=identity.role,
            familiarity=min(1.0, self.familiarity + 0.02),
            interaction_count=self.interaction_count + 1,
            last_interaction_at=(
                max(self.last_interaction_at, occurred_at)
                if self.last_interaction_at is not None
                else occurred_at
            ),
            last_event_id=event_id,
        )

    def as_context(self) -> dict[str, object]:
        return {
            "counterpart_id": self.counterpart_id,
            "display_name": self.display_name,
            "role": self.role,
            "familiarity": self.familiarity,
            "trust": self.trust,
            "affinity": self.affinity,
            "interaction_count": self.interaction_count,
            "last_interaction_at": (
                self.last_interaction_at.isoformat()
                if self.last_interaction_at is not None
                else None
            ),
        }

    @staticmethod
    def _validate_range(
        name: str, value: float, minimum: float, maximum: float
    ) -> None:
        if value < minimum or value > maximum:
            raise ValueError(f"{name}は{minimum}以上{maximum}以下にしてください。")


@dataclass(frozen=True, slots=True)
class RelationshipMemory:
    """相手IDごとのRelationshipStateをimmutableに保持する。"""

    relationships: tuple[RelationshipState, ...] = ()
    current_counterpart_id: str | None = None
    max_entries: int = 1000

    def __post_init__(self) -> None:
        if self.max_entries <= 0:
            raise ValueError("max_entriesは1以上にしてください。")
        if len(self.relationships) > self.max_entries:
            raise ValueError("relationshipsがmax_entriesを超えています。")

    def get(self, counterpart_id: str) -> RelationshipState | None:
        return next(
            (
                item
                for item in self.relationships
                if item.counterpart_id == counterpart_id
            ),
            None,
        )

    @property
    def current(self) -> RelationshipState | None:
        if self.current_counterpart_id is None:
            return None
        return self.get(self.current_counterpart_id)

    def record(
        self,
        identity: RelationshipIdentity,
        *,
        event_id: str,
        occurred_at: datetime | None = None,
    ) -> RelationshipMemory:
        occurred_at = occurred_at or datetime.now(timezone.utc)
        existing = self.get(identity.counterpart_id) or RelationshipState(
            counterpart_id=identity.counterpart_id,
            display_name=identity.display_name,
            role=identity.role,
        )
        updated = existing.record_interaction(
            identity,
            event_id=event_id,
            occurred_at=occurred_at,
        )
        others = tuple(
            item
            for item in self.relationships
            if item.counterpart_id != identity.counterpart_id
        )
        relationships = (*others, updated)
        return RelationshipMemory(
            relationships=relationships[-self.max_entries :],
            current_counterpart_id=identity.counterpart_id,
            max_entries=self.max_entries,
        )
