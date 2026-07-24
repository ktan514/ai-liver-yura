from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock
from typing import ClassVar

from app.domain.activity_constraints import ActivityConstraintValidator
from app.shared.contracts.activity import (
    ActivityDefinition,
    ActivityMatcher,
    ActivityMatcherContext,
    ActivityOperation,
    DeterministicActivityMatch,
    OngoingActivityPlanningContext,
)
from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class LegacyActivityMatcherAdapter:
    """Deprecated marker入力を共通ActivityMatcher契約へ変換する互換Adapter。

    legacy fieldsを利用するPluginがなくなり、migration testを削除できる段階で
    このAdapterとActivityDefinition上の互換fieldsを同時に削除する。
    """

    activity_type: str
    display_name: str
    start_markers: tuple[str, ...]
    stop_markers: tuple[str, ...]
    matcher_id: str

    _warned_definitions: ClassVar[set[str]] = set()
    _warning_lock: ClassVar[RLock] = RLock()

    @classmethod
    def from_definition(
        cls, definition: ActivityDefinition
    ) -> LegacyActivityMatcherAdapter | None:
        if not definition.start_markers and not definition.stop_markers:
            return None
        matcher_id = (
            f"legacy:{definition.provider_plugin_id}:{definition.activity_type}"
        )
        with cls._warning_lock:
            first_warning = matcher_id not in cls._warned_definitions
            cls._warned_definitions.add(matcher_id)
        logger = TraceLogger()
        if first_warning:
            logger.info(
                "activity_matcher:legacy_adapter_registered",
                matcher_id=matcher_id,
                activity_type=definition.activity_type,
                deprecated=True,
                warning_suppressed=False,
            )
        else:
            logger.debug(
                "activity_matcher:legacy_warning_suppressed",
                matcher_id=matcher_id,
                activity_type=definition.activity_type,
                warning_suppressed=True,
            )
        return cls(
            activity_type=definition.activity_type,
            display_name=definition.display_name,
            start_markers=definition.start_markers,
            stop_markers=definition.stop_markers,
            matcher_id=matcher_id,
        )

    def match(
        self, context: ActivityMatcherContext
    ) -> DeterministicActivityMatch | None:
        if context.normalized_input in self.start_markers:
            operation = ActivityOperation.START
        elif context.normalized_input in self.stop_markers:
            operation = ActivityOperation.STOP
        else:
            return None
        TraceLogger().info(
            "activity_matcher:legacy_matcher_used",
            matcher_id=self.matcher_id,
            activity_type=self.activity_type,
            evidence=context.normalized_input,
        )
        action = "開始" if operation == ActivityOperation.START else "停止"
        return DeterministicActivityMatch(
            activity_type=self.activity_type,
            operation=operation,
            goal=f"{self.display_name}を{action}する",
            confidence=0.99,
            reason="legacy_activity_matcher_adapter",
            evidence=context.normalized_input,
            matcher_id=self.matcher_id,
            matcher_type="legacy_adapter",
            priority=100,
        )

    @classmethod
    def reset_warning_state_for_testing(cls) -> None:
        with cls._warning_lock:
            cls._warned_definitions.clear()


class ActivityMatcherResolver:
    """全Matcherを共通契約で評価し、優先順位と競合を安全に解決する。"""

    def __init__(
        self, constraint_validator: ActivityConstraintValidator | None = None
    ) -> None:
        self._constraint_validator = (
            constraint_validator or ActivityConstraintValidator()
        )
        self._trace_logger = TraceLogger()

    def resolve(
        self,
        user_input: str,
        definitions: tuple[ActivityDefinition, ...],
        *,
        ongoing_activity: OngoingActivityPlanningContext | None = None,
        conversation_context: dict[str, object] | None = None,
    ) -> tuple[ActivityDefinition, DeterministicActivityMatch] | None:
        normalized = user_input.strip().rstrip("。！!")
        correlation = {
            key: value
            for key in (
                "trace_id",
                "parent_trace_id",
                "source_event_id",
                "activity_turn_id",
                "ongoing_activity_id",
                "confirmation_id",
            )
            if (value := (conversation_context or {}).get(key)) is not None
        }
        candidates: list[tuple[ActivityDefinition, DeterministicActivityMatch]] = []
        for definition in definitions:
            context = ActivityMatcherContext(
                user_input=user_input,
                normalized_input=normalized,
                ongoing_activity=ongoing_activity,
                activity_definition=definition,
                registered_activity_definitions=definitions,
                conversation_context=conversation_context or {},
            )
            for matcher in self._matchers(definition):
                match = matcher.match(context)
                if match is None:
                    continue
                normalized_match = replace(
                    match,
                    activity_type=definition.activity_type,
                    matcher_id=(
                        match.matcher_id
                        if match.matcher_id != "anonymous_matcher"
                        else f"{definition.provider_plugin_id}:{type(matcher).__name__}"
                    ),
                )
                validation = self._constraint_validator.validate(
                    normalized_match.constraints,
                    definition.constraints_schema,
                    schema_version=definition.constraints_schema_version,
                )
                self._trace_logger.debug(
                    "activity_matcher:candidate",
                    **correlation,
                    matcher_id=normalized_match.matcher_id,
                    matcher_type=normalized_match.matcher_type,
                    priority=normalized_match.priority,
                    confidence=normalized_match.confidence,
                    evidence=normalized_match.evidence,
                    activity_type=definition.activity_type,
                    constraints_valid=validation.valid,
                    constraint_errors=[error.code for error in validation.errors],
                )
                if not validation.valid:
                    continue
                candidates.append(
                    (
                        definition,
                        replace(
                            normalized_match,
                            constraints=dict(validation.normalized_constraints),
                        ),
                    )
                )
        selected = self._select(candidates)
        self._trace_logger.debug(
            "activity_matcher:resolved",
            **correlation,
            candidate_count=len(candidates),
            selected_matcher=selected[1].matcher_id if selected is not None else None,
            rejected_candidates=[
                item.matcher_id
                for _, item in candidates
                if selected is None or item.matcher_id != selected[1].matcher_id
            ],
        )
        return selected

    @staticmethod
    def _matchers(definition: ActivityDefinition) -> tuple[ActivityMatcher, ...]:
        explicit = definition.matchers
        if definition.matcher is not None and all(
            matcher is not definition.matcher for matcher in explicit
        ):
            explicit = (*explicit, definition.matcher)
        legacy = LegacyActivityMatcherAdapter.from_definition(definition)
        return (*explicit, legacy) if legacy is not None else explicit

    @staticmethod
    def _select(
        candidates: list[tuple[ActivityDefinition, DeterministicActivityMatch]],
    ) -> tuple[ActivityDefinition, DeterministicActivityMatch] | None:
        if not candidates:
            return None
        highest_priority = max(match.priority for _, match in candidates)
        prioritized = [
            item for item in candidates if item[1].priority == highest_priority
        ]
        if len(prioritized) == 1:
            return prioritized[0]
        highest_confidence = max(match.confidence for _, match in prioritized)
        confident = [
            item for item in prioritized if item[1].confidence == highest_confidence
        ]
        if len(confident) != 1:
            return None
        return confident[0]
