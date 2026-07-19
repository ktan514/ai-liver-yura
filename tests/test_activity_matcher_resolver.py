from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path

from app.domain.behavior import (
    ActivityDefinition,
    ActivityMatcher,
    ActivityMatcherContext,
    ActivityOperation,
    DeterministicActivityMatch,
)
from app.plugins.games.plugin import GamesPlugin
from app.runtime import (
    behavior_planner,
    ongoing_input,
    runtime_coordinator,
    situation_evaluator,
)
from app.runtime.activity_matcher_resolver import (
    ActivityMatcherResolver,
    LegacyActivityMatcherAdapter,
)
from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class FixedMatcher:
    operation: ActivityOperation
    confidence: float = 0.99
    matcher_id: str = "test.plugin"
    priority: int = 300
    constraints: dict[str, object] | None = None

    def match(
        self, context: ActivityMatcherContext
    ) -> DeterministicActivityMatch | None:
        if context.normalized_input != "一致":
            return None
        return DeterministicActivityMatch(
            operation=self.operation,
            goal="共通Matcherで処理する",
            constraints=self.constraints or {},
            confidence=self.confidence,
            evidence=context.normalized_input,
            matcher_id=self.matcher_id,
            matcher_type="plugin",
            priority=self.priority,
        )


def _definition(
    *,
    activity_type: str = "dummy",
    display_name: str = "ダミー",
    required_capability: str = "dummy.execute",
    provider_plugin_id: str = "dummy",
    start_markers: tuple[str, ...] = (),
    stop_markers: tuple[str, ...] = (),
    matchers: tuple[ActivityMatcher, ...] = (),
    constraints_schema: dict[str, object] | None = None,
) -> ActivityDefinition:
    return ActivityDefinition(
        activity_type=activity_type,
        display_name=display_name,
        required_capability=required_capability,
        provider_plugin_id=provider_plugin_id,
        start_markers=start_markers,
        stop_markers=stop_markers,
        supported_operations=(
            ActivityOperation.START,
            ActivityOperation.CONTINUE,
            ActivityOperation.STOP,
        ),
        matchers=matchers,
        constraints_schema=constraints_schema or {},
    )


def test_legacy_start_and_stop_are_adapted_with_evidence() -> None:
    definition = _definition(
        start_markers=("始める",),
        stop_markers=("止める",),
    )
    resolver = ActivityMatcherResolver()

    started = resolver.resolve("始める", (definition,))
    stopped = resolver.resolve("止める", (definition,))

    assert started is not None
    assert started[1].operation == ActivityOperation.START
    assert started[1].matcher_type == "legacy_adapter"
    assert started[1].evidence == "始める"
    assert stopped is not None
    assert stopped[1].operation == ActivityOperation.STOP
    assert stopped[1].evidence == "止める"


def test_legacy_deprecation_warning_is_not_repeated(
    tmp_path: Path,
) -> None:
    LegacyActivityMatcherAdapter.reset_warning_state_for_testing()
    trace_file = tmp_path / "trace.log"
    TraceLogger.configure(level="INFO", trace_file_path=trace_file)
    definition = _definition(start_markers=("始める",))
    resolver = ActivityMatcherResolver()
    try:
        resolver.resolve("対象外", (definition,))
        resolver.resolve("対象外", (definition,))
        log = trace_file.read_text(encoding="utf-8")
        assert log.count("activity_matcher:legacy_adapter_registered") == 1
    finally:
        TraceLogger.configure(level="INFO", trace_file_path=tmp_path / "restored.log")


def test_plugin_matcher_has_priority_over_legacy_adapter() -> None:
    definition = _definition(
        start_markers=("一致",),
        matchers=(FixedMatcher(ActivityOperation.STOP),),
    )

    selected = ActivityMatcherResolver().resolve("一致", (definition,))

    assert selected is not None
    assert selected[1].operation == ActivityOperation.STOP
    assert selected[1].matcher_id == "test.plugin"
    assert selected[1].matcher_type == "plugin"


def test_equal_priority_and_confidence_conflict_falls_back_safely() -> None:
    definition = _definition(
        matchers=(
            FixedMatcher(ActivityOperation.START, matcher_id="first"),
            FixedMatcher(ActivityOperation.STOP, matcher_id="second"),
        )
    )

    assert ActivityMatcherResolver().resolve("一致", (definition,)) is None


def test_invalid_matcher_constraints_are_not_selected() -> None:
    definition = _definition(
        matchers=(FixedMatcher(ActivityOperation.START, constraints={"query": []}),),
        constraints_schema={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        },
    )

    assert ActivityMatcherResolver().resolve("一致", (definition,)) is None


def test_new_matcher_contract_is_activity_agnostic() -> None:
    search = _definition(
        activity_type="external_search",
        display_name="検索",
        required_capability="search.execute",
        provider_plugin_id="search",
        matchers=(FixedMatcher(ActivityOperation.START),),
    )

    selected = ActivityMatcherResolver().resolve("一致", (search,))

    assert selected is not None
    assert selected[0].activity_type == "external_search"
    assert selected[1].activity_type == "external_search"


def test_games_plugin_uses_only_new_matcher_for_start_stop_and_continue() -> None:
    definition = GamesPlugin().activity_definitions()[0]

    assert definition.start_markers == ()
    assert definition.stop_markers == ()
    assert definition.matcher is None
    assert len(definition.matchers) == 1
    resolver = ActivityMatcherResolver()
    operations: dict[str, ActivityOperation] = {}
    for text in ("しりとりしよう", "しりとりをやめよう", "しりとりを続けよう"):
        selected = resolver.resolve(text, (definition,))
        assert selected is not None
        operations[text] = selected[1].operation
    assert operations == {
        "しりとりしよう": ActivityOperation.START,
        "しりとりをやめよう": ActivityOperation.STOP,
        "しりとりを続けよう": ActivityOperation.CONTINUE,
    }


def test_core_runtime_modules_do_not_reference_legacy_marker_fields() -> None:
    for module in (
        situation_evaluator,
        behavior_planner,
        runtime_coordinator,
        ongoing_input,
    ):
        source = inspect.getsource(module)
        assert "start_markers" not in source
        assert "stop_markers" not in source
