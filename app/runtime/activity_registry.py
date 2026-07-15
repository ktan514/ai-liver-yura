from __future__ import annotations

from collections.abc import Callable, Iterable

from app.domain.behavior import ActivityDefinition
from app.utils.trace import TraceLogger


class ActivityRegistry:
    """認識可能なActivity定義をCapabilityの可用性とは分離して管理する。"""

    def __init__(
        self,
        definitions: Iterable[ActivityDefinition] | Callable[[], tuple[ActivityDefinition, ...]],
    ) -> None:
        self._source = definitions
        self._trace_logger = TraceLogger()

    def list_definitions(self) -> tuple[ActivityDefinition, ...]:
        definitions = self._source() if callable(self._source) else tuple(self._source)
        seen: set[str] = set()
        for definition in definitions:
            if definition.activity_type in seen:
                raise ValueError(f"Activity定義が重複しています: {definition.activity_type}")
            seen.add(definition.activity_type)
        self._trace_logger.debug(
            "activity_registry:definitions_listed",
            activity_types=sorted(seen),
            definition_count=len(definitions),
        )
        return tuple(definitions)

    def resolve(self, activity_type: str) -> ActivityDefinition | None:
        definition = next(
            (
                definition
                for definition in self.list_definitions()
                if definition.activity_type == activity_type
            ),
            None,
        )
        self._trace_logger.debug(
            "activity_registry:resolved",
            activity_type=activity_type,
            found=definition is not None,
        )
        return definition
