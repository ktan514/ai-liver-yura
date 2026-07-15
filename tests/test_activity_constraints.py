from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.domain.activity_constraints import (
    ActivityConstraintValidator,
    LegacyConstraintSchemaAdapter,
)
from app.domain.behavior import (
    ActivityDefinition,
    ActivityMatcherContext,
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
    DeterministicActivityMatch,
)
from app.domain.pending_confirmation import (
    ConfirmationResolution,
    ConfirmationResolutionKind,
)
from app.ports.llm_roles import ResponseGeneratorRoleAdapter
from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner
from app.runtime.pending_confirmation import PendingConfirmationManager
from app.runtime.situation_evaluator import SituationEvaluator
from tests.test_behavior_planner import StubResponseGenerator

STRICT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["name", "enabled", "count", "ratio", "tags", "options"],
    "properties": {
        "name": {"type": "string", "minLength": 2, "maxLength": 8},
        "enabled": {"type": "boolean"},
        "count": {"type": "integer", "minimum": 1, "maximum": 5},
        "ratio": {"type": "number", "minimum": 0, "maximum": 1},
        "mode": {"type": "string", "enum": ["safe", "fast"], "default": "safe"},
        "nullable": {"type": "string", "nullable": True},
        "tags": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {"type": "string"},
        },
        "options": {
            "type": "object",
            "required": ["level"],
            "properties": {"level": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


def _valid() -> dict[str, object]:
    return {
        "name": "test",
        "enabled": True,
        "count": 2,
        "ratio": 0.5,
        "tags": ["a"],
        "options": {"level": 1},
    }


def _definition(schema: dict[str, object] | None = None, version: str = "2") -> ActivityDefinition:
    return ActivityDefinition(
        activity_type="external_search",
        display_name="外部検索",
        required_capability="search.execute",
        provider_plugin_id="search",
        supported_operations=(ActivityOperation.START,),
        constraints_schema=schema or STRICT_SCHEMA,
        constraints_schema_version=version,
    )


def test_strict_schema_validates_types_defaults_nested_objects_and_arrays() -> None:
    result = ActivityConstraintValidator().validate(_valid(), STRICT_SCHEMA, schema_version="2")

    assert result.valid is True
    assert result.normalized_constraints["mode"] == "safe"
    assert result.applied_defaults == {"mode": "safe"}
    assert result.schema_version == "2"
    assert result.as_validated() is not None


@pytest.mark.parametrize(
    ("updates", "code", "path"),
    [
        ({"name": 1}, "invalid_type", "name"),
        ({"enabled": "yes"}, "invalid_type", "enabled"),
        ({"count": 1.5}, "invalid_type", "count"),
        ({"ratio": "0.5"}, "invalid_type", "ratio"),
        ({"name": "x"}, "min_length", "name"),
        ({"count": 9}, "maximum", "count"),
        ({"tags": []}, "min_items", "tags"),
        ({"tags": ["a", "b", "c"]}, "max_items", "tags"),
        ({"tags": [1]}, "invalid_type", "tags.0"),
        ({"options": {}}, "required", "options.level"),
        ({"options": {"level": 1, "unknown": True}}, "additional_property", "options.unknown"),
        ({"unknown": True}, "additional_property", "unknown"),
    ],
)
def test_strict_schema_reports_structured_errors(
    updates: dict[str, object], code: str, path: str
) -> None:
    result = ActivityConstraintValidator().validate({**_valid(), **updates}, STRICT_SCHEMA)

    assert result.valid is False
    assert any(error.code == code and error.path == path for error in result.errors)


def test_required_optional_nullable_and_explicit_default_are_distinct() -> None:
    missing = _valid()
    del missing["name"]
    missing_result = ActivityConstraintValidator().validate(missing, STRICT_SCHEMA)
    nullable_result = ActivityConstraintValidator().validate(
        {**_valid(), "nullable": None}, STRICT_SCHEMA
    )

    assert any(error.code == "required" and error.path == "name" for error in missing_result.errors)
    assert (
        "nullable"
        not in ActivityConstraintValidator().validate(_valid(), STRICT_SCHEMA).applied_defaults
    )
    assert nullable_result.valid is True

    not_nullable = ActivityConstraintValidator().validate(
        {"value": None},
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    multiple_types = ActivityConstraintValidator().validate(
        {"value": 1},
        {
            "type": "object",
            "properties": {"value": {"type": ["string", "integer"]}},
        },
    )
    assert not_nullable.errors[0].code == "invalid_type"
    assert multiple_types.valid is True


def test_additional_properties_can_be_true_or_a_schema() -> None:
    validator = ActivityConstraintValidator()
    allowed = validator.validate(
        {"anything": object()}, {"type": "object", "additionalProperties": True}
    )
    typed = validator.validate(
        {"score": "high"},
        {"type": "object", "additionalProperties": {"type": "integer"}},
    )

    assert allowed.valid is True
    assert typed.valid is False
    assert typed.errors[0].path == "score"


def test_same_validator_supports_stream_control_constraints() -> None:
    schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {"type": "string", "enum": ["start", "stop"]},
            "metadata": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }

    accepted = ActivityConstraintValidator().validate(
        {"operation": "stop", "metadata": {"reason": "finished"}}, schema
    )
    rejected = ActivityConstraintValidator().validate({"operation": "delete"}, schema)

    assert accepted.valid is True
    assert rejected.errors[0].code == "enum"


def test_legacy_schema_adapter_is_explicit_and_deprecated() -> None:
    schema, warnings = LegacyConstraintSchemaAdapter().adapt({"theme": "string"})
    valid = ActivityConstraintValidator().validate({"theme": "sea"}, {"theme": "string"})
    invalid = ActivityConstraintValidator().validate({"theme": []}, {"theme": "string"})

    assert schema["type"] == "object"
    assert warnings == ("legacy_constraint_schema_deprecated",)
    assert valid.valid is True
    assert invalid.errors[0].code == "invalid_type"


def test_situation_and_behavior_planner_preserve_candidate_but_ask_for_invalid_constraints() -> (
    None
):
    definition = _definition(
        {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        }
    )
    raw = json.dumps(
        {
            "activity_type": "external_search",
            "operation": "start",
            "goal": "検索する",
            "constraints": {"query": ["invalid"]},
            "speech_act": "request",
            "negated": False,
            "hypothetical": False,
            "past_reference": False,
            "knowledge_question": False,
            "confidence": 0.99,
            "reason": "test",
        }
    )
    evaluator = SituationEvaluator(ResponseGeneratorRoleAdapter(StubResponseGenerator(raw)))
    analysis = evaluator.parse(raw, (definition,))
    assert analysis is not None
    context = BehaviorPlanningContext(
        user_text="検索して",
        source_event_id="event-1",
        available_capabilities=frozenset({"search.execute"}),
        activity_definitions=(definition,),
    )

    plan = BehaviorPlanner(StubResponseGenerator(raw)).plan_from_analysis(context, analysis)

    assert analysis.constraint_errors[0].code == "invalid_type"
    assert plan.decision == BehaviorDecision.ASK_CONFIRMATION
    assert plan.activity_type == "external_search"
    assert plan.constraint_errors


@pytest.mark.asyncio
async def test_deterministic_matcher_output_is_validated_by_the_same_schema() -> None:
    class InvalidMatcher:
        def match(self, context: ActivityMatcherContext) -> DeterministicActivityMatch | None:
            return DeterministicActivityMatch(
                operation=ActivityOperation.START,
                goal="開始する",
                constraints={"query": ["invalid"]},
            )

    definition = replace(
        _definition(
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "additionalProperties": False,
            }
        ),
        matcher=InvalidMatcher(),
    )
    context = BehaviorPlanningContext(
        user_text="確実な開始表現",
        source_event_id="event-1",
        available_capabilities=frozenset(),
        activity_definitions=(definition,),
    )
    evaluator = SituationEvaluator(ResponseGeneratorRoleAdapter(StubResponseGenerator("unused")))

    analysis = await evaluator.evaluate(context)

    assert analysis.evaluator_type == "fallback"
    assert analysis.activity_candidate is None


def test_activity_plan_validator_revalidates_and_marks_constraints_as_validated() -> None:
    definition = _definition()

    def definitions() -> tuple[ActivityDefinition, ...]:
        return (definition,)

    validator = ActivityPlanValidator(lambda *_: True, definitions)
    plan = ActivityPlan(
        decision=BehaviorDecision.START_ACTIVITY,
        activity_type=definition.activity_type,
        goal="test",
        required_capability=definition.required_capability,
        provider_plugin_id=definition.provider_plugin_id,
        operation=ActivityOperation.START,
        constraints=_valid(),
        constraints_schema_version="2",
    )

    accepted = validator.validate(plan)
    rejected = validator.validate(replace(plan, constraints={"name": []}))
    stale = validator.validate(replace(plan, constraints_schema_version="1"))

    assert accepted.accepted is True
    assert accepted.plan.validated_constraints is not None
    assert accepted.plan.constraints["mode"] == "safe"
    assert rejected.accepted is False
    assert rejected.result.data["reason"] == "constraints_invalid"
    assert stale.accepted is False
    assert stale.result.data["reason"] == "constraints_schema_version_mismatch"


def test_pending_confirmation_validates_clarification_before_candidate_update() -> None:
    schema = {
        "type": "object",
        "required": ["theme"],
        "properties": {"theme": {"type": "string", "minLength": 1}},
        "additionalProperties": False,
    }
    definition = _definition(schema)
    validator = ActivityPlanValidator(lambda *_: True, lambda: (definition,))
    plan = ActivityPlan(
        decision=BehaviorDecision.ASK_CONFIRMATION,
        activity_type=definition.activity_type,
        goal="条件を確認する",
        required_capability=definition.required_capability,
        provider_plugin_id=definition.provider_plugin_id,
        operation=ActivityOperation.START,
        constraints={},
        constraint_errors=ActivityConstraintValidator().validate({}, schema).errors,
        constraints_schema_version="2",
    )
    manager = PendingConfirmationManager(max_attempts=3)
    pending = manager.create(
        plan,
        source_event_id="event-1",
        current_ongoing_activity_id=None,
        context_snapshot={},
    )
    assert pending.confirmation_type.value == "confirm_constraints"
    invalid = ConfirmationResolution(
        ConfirmationResolutionKind.CLARIFICATION,
        1.0,
        "test",
        constraint_updates={"theme": []},
    )
    valid = replace(invalid, constraint_updates={"theme": "深海魚"})

    still_pending = manager.revise(
        pending,
        invalid,
        source_event_id="event-2",
        constraint_validation=validator.validate_constraints,
    )
    assert still_pending is not None
    assert still_pending.candidate_constraints == {}
    revised = manager.revise(
        still_pending,
        valid,
        source_event_id="event-3",
        constraint_validation=validator.validate_constraints,
    )

    assert revised is not None
    assert revised.candidate_constraints == {"theme": "深海魚"}
    assert revised.candidate_plan.validated_constraints is not None
