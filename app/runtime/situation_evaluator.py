from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import Any

from app.core.plugins.user_request import UserRequestKind, interpret_user_request
from app.domain.activities import Activity, ActivityType
from app.domain.activity_constraints import ActivityConstraintValidator
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    BehaviorPlanningContext,
    OngoingInputDecision,
    SituationAnalysis,
    SpeechAct,
)
from app.ports.llm_roles import SituationEvaluationModel
from app.ports.prompt_builder import SituationPromptBuilder
from app.runtime.activity_matcher_resolver import ActivityMatcherResolver
from app.utils.trace import TraceLogger


class SituationEvaluator:
    """Eventの意味だけを評価し、Capabilityや実行方針には関与しない。"""

    def __init__(
        self,
        model: SituationEvaluationModel,
        *,
        prompt_builder: SituationPromptBuilder,
        confidence_threshold: float = 0.85,
        max_attempts: int = 1,
        constraint_validator: ActivityConstraintValidator | None = None,
        matcher_resolver: ActivityMatcherResolver | None = None,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                "confidence_threshold は0.0以上1.0以下で指定してください。"
            )
        if max_attempts < 1:
            raise ValueError("max_attempts は1以上で指定してください。")
        self._model = model
        self._confidence_threshold = confidence_threshold
        self._max_attempts = max_attempts
        self._prompt_builder = prompt_builder
        self._constraint_validator = (
            constraint_validator or ActivityConstraintValidator()
        )
        self._matcher_resolver = matcher_resolver or ActivityMatcherResolver(
            self._constraint_validator
        )
        self._trace_logger = TraceLogger()

    async def evaluate(self, context: BehaviorPlanningContext) -> SituationAnalysis:
        self._trace_logger.debug(
            "situation_evaluator:evaluation_started",
            source_event_id=context.source_event_id,
            candidate_activity_types=[
                item.activity_type for item in context.activity_definitions
            ],
            ongoing_activity_type=context.ongoing_activity_type,
        )
        definitions = self._candidate_definitions(context)
        if context.event_type != "user_text":
            semantic = await self._evaluate_with_llm(
                replace(context, activity_definitions=definitions)
            )
            if semantic is not None:
                return semantic
            return SituationAnalysis(
                activity_candidate=(
                    definitions[0].activity_type if len(definitions) == 1 else None
                ),
                operation=ActivityOperation.START,
                goal="現在状態に応じたActivityを開始する",
                confidence=0.0,
                reason="system_event_evaluation_failed",
                evaluator_type="fallback",
            )
        request = interpret_user_request(context.user_text)
        if self._is_negated_expression(context.user_text):
            request = replace(
                request,
                kind=UserRequestKind.NEGATIVE,
                confidence=max(request.confidence, 0.95),
                reason="negative_expression",
            )
        non_execution = self._non_execution(
            context.user_text, request.kind, request.reason
        )
        if non_execution is not None:
            return non_execution

        deterministic = self._deterministic(context, definitions)
        if deterministic is not None:
            return deterministic

        if context.instruction_trusted and self._is_administrative_direction(
            context.user_text, request.kind
        ):
            return SituationAnalysis(
                activity_candidate=None,
                operation=ActivityOperation.DISCUSS,
                goal="管理者の自然文による進行指示に沿って、その場のトークを行う",
                speech_act=SpeechAct.COMMAND,
                confidence=max(request.confidence, 0.95),
                reason="trusted_administrator_direction",
                evaluator_type="administrator_direction",
            )

        semantic = await self._evaluate_with_llm(
            replace(
                context,
                request_kind=request.kind.value,
                activity_definitions=definitions,
            )
        )
        if semantic is not None:
            return semantic

        if (
            context.ongoing_activity is not None
            or context.ongoing_activity_type is not None
            or context.active_activity_definition is not None
        ):
            return SituationAnalysis(
                activity_candidate=None,
                operation=None,
                goal="進行中Activityに対する意図を確認する",
                speech_act=self._speech_act(context.user_text),
                confidence=0.0,
                reason="ongoing_input_semantics_unresolved",
                evaluator_type="ongoing_fallback",
                ongoing_input_decision=OngoingInputDecision.ASK_CONFIRMATION,
            )

        return SituationAnalysis(
            activity_candidate=None,
            operation=ActivityOperation.DISCUSS,
            goal="ユーザー入力について会話する",
            speech_act=self._speech_act(context.user_text),
            confidence=request.confidence,
            reason=request.reason,
            evaluator_type="fallback",
        )

    async def _evaluate_with_llm(
        self, context: BehaviorPlanningContext
    ) -> SituationAnalysis | None:
        prompt = self._prompt_builder.build(context)
        self._trace_logger.debug(
            "behavior_planner:llm_candidates",
            source_event_id=context.source_event_id,
            candidates=[item.activity_type for item in context.activity_definitions],
        )
        for attempt in range(self._max_attempts):
            activity = Activity(
                activity_type=ActivityType.BEHAVIOR_PLANNING,
                goal="ユーザー入力の状況と意味を構造化する",
                context={
                    "plugin_prompt_override": prompt,
                    "llm_role": "situation_evaluator",
                    "event_id": context.source_event_id,
                    "user_input": context.user_text,
                    "planner_state": {
                        "ongoing_activity_type": context.ongoing_activity_type,
                        "ongoing_activity": (
                            asdict(context.ongoing_activity)
                            if context.ongoing_activity is not None
                            else None
                        ),
                        "active_activity_definition": (
                            {
                                "activity_type": context.active_activity_definition.activity_type,
                                "supported_operations": [
                                    operation.value
                                    for operation in (
                                        context.active_activity_definition.supported_operations
                                    )
                                ],
                            }
                            if context.active_activity_definition is not None
                            else None
                        ),
                        "drive": context.drive,
                        "emotion": context.emotion,
                        "last_activity_result": context.last_activity_result,
                    },
                    "constraints": [
                        "発話本文を生成しない",
                        "Capabilityの可用性や実行成功を判断しない",
                        "候補外のActivityを生成しない",
                    ],
                    "trace_context": context.trace_context,
                    "llm_attempt": attempt + 1,
                },
                source_event_id=context.source_event_id,
            )
            try:
                raw = await self._model.evaluate(activity)
            except Exception as error:
                self._trace_logger.warning(
                    "situation_evaluator:model_failed",
                    error_type=type(error).__name__,
                    attempt=attempt,
                )
                return None
            analysis = self.parse(
                raw,
                context.activity_definitions,
                intent_flags_can_cancel_activity=context.event_type
                != "curiosity_peak",
            )
            self._trace_logger.llm_response(
                purpose="behavior_planning",
                provider="situation_evaluator",
                model=type(self._model).__name__,
                activity_id=activity.activity_id,
                raw_response=raw,
                parsed_response=(
                    {
                        **asdict(analysis),
                        "activity_type": analysis.activity_candidate or "conversation",
                    }
                    if analysis is not None
                    else None
                ),
                fallback_used=analysis is None,
                stage="parsed" if analysis is not None else "schema_validation_failed",
                llm_role="situation_evaluator",
                service="situation_evaluator",
                trace_id=(
                    context.trace_context.trace_id if context.trace_context else None
                ),
                parent_trace_id=(
                    context.trace_context.parent_trace_id
                    if context.trace_context
                    else None
                ),
                source_event_id=context.source_event_id,
                activity_turn_id=(
                    context.trace_context.activity_turn_id
                    if context.trace_context
                    else None
                ),
                attempt=attempt + 1,
            )
            if analysis is None:
                continue
            if analysis.confidence < self._confidence_threshold:
                return replace(analysis, reason="semantic_confidence_below_threshold")
            return analysis
        return None

    def parse(
        self,
        raw: str,
        definitions: tuple[ActivityDefinition, ...] = (),
        *,
        intent_flags_can_cancel_activity: bool = True,
    ) -> SituationAnalysis | None:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or lines[-1].strip() != "```":
                return None
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            payload: Any = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        required = {
            "activity_type",
            "operation",
            "goal",
            "constraints",
            "speech_act",
            "negated",
            "hypothetical",
            "past_reference",
            "knowledge_question",
            "confidence",
            "reason",
        }
        if not isinstance(payload, dict) or not required.issubset(payload):
            return None
        try:
            operation = (
                ActivityOperation(str(payload["operation"]))
                if payload["operation"] is not None
                else None
            )
            speech_act = SpeechAct(str(payload["speech_act"]))
            ongoing_input_decision = (
                OngoingInputDecision(str(payload["ongoing_input_decision"]))
                if payload.get("ongoing_input_decision") is not None
                else None
            )
        except ValueError:
            return None
        constraints = payload["constraints"]
        confidence = payload["confidence"]
        flags = ("negated", "hypothetical", "past_reference", "knowledge_question")
        if not isinstance(constraints, dict) or not all(
            isinstance(key, str) for key in constraints
        ):
            return None
        if not all(isinstance(payload[field], bool) for field in flags):
            return None
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return None
        if not 0.0 <= float(confidence) <= 1.0:
            return None
        activity_type = str(payload["activity_type"])
        flags_force_conversation = intent_flags_can_cancel_activity and any(
            bool(payload[field]) for field in flags
        )
        candidate = (
            None
            if activity_type == "conversation" or flags_force_conversation
            else activity_type
        )
        definition = next(
            (item for item in definitions if item.activity_type == candidate), None
        )
        if candidate is not None and definition is None:
            return None
        if definition is not None and operation not in definition.supported_operations:
            return None
        if flags_force_conversation:
            if bool(payload["negated"]) or bool(payload["past_reference"]):
                operation = None
            elif operation not in {
                ActivityOperation.EXPLAIN,
                ActivityOperation.DISCUSS,
            }:
                operation = ActivityOperation.DISCUSS
        elif candidate is None and operation not in {
            None,
            ActivityOperation.EXPLAIN,
            ActivityOperation.DISCUSS,
        }:
            return None
        validation = (
            self._constraint_validator.validate(
                constraints,
                definition.constraints_schema,
                schema_version=definition.constraints_schema_version,
            )
            if definition is not None
            else None
        )
        if validation is not None:
            self._trace_logger.debug(
                "activity_constraints:validated",
                activity_type=(
                    definition.activity_type if definition is not None else None
                ),
                validation_stage="situation_analysis",
                source="llm",
                schema_version=validation.schema_version,
                valid=validation.valid,
                normalized_constraints=validation.normalized_constraints,
                error_paths=[error.path for error in validation.errors],
                error_codes=[error.code for error in validation.errors],
                applied_defaults=validation.applied_defaults,
                warnings=list(validation.warnings),
            )
        return SituationAnalysis(
            activity_candidate=candidate,
            operation=operation,
            goal=str(payload["goal"]),
            constraints=(
                dict(validation.normalized_constraints)
                if validation is not None
                else dict(constraints)
            ),
            speech_act=speech_act,
            negated=bool(payload["negated"]),
            hypothetical=bool(payload["hypothetical"]),
            past_reference=bool(payload["past_reference"]),
            knowledge_question=bool(payload["knowledge_question"]),
            confidence=float(confidence),
            reason=str(payload["reason"]),
            evaluator_type="llm",
            ongoing_input_decision=ongoing_input_decision,
            constraint_errors=validation.errors if validation is not None else (),
            constraints_schema_version=(
                validation.schema_version if validation is not None else None
            ),
        )

    @staticmethod
    def _candidate_definitions(
        context: BehaviorPlanningContext,
    ) -> tuple[ActivityDefinition, ...]:
        definitions = list(context.activity_definitions)
        active = context.active_activity_definition
        if active is not None and not any(
            item.activity_type == active.activity_type for item in definitions
        ):
            definitions.insert(0, active)
        return tuple(definitions)

    def _deterministic(
        self,
        context: BehaviorPlanningContext,
        definitions: tuple[ActivityDefinition, ...],
    ) -> SituationAnalysis | None:
        resolved = self._matcher_resolver.resolve(
            context.user_text,
            definitions,
            ongoing_activity=context.ongoing_activity,
            conversation_context={
                "source_event_id": context.source_event_id,
                "ongoing_activity_type": context.ongoing_activity_type,
                **(
                    context.trace_context.as_log_fields()
                    if context.trace_context
                    else {}
                ),
            },
        )
        if resolved is None:
            self._trace_logger.debug(
                "situation_evaluator:deterministic_match",
                matched=False,
            )
            return None
        definition, match = resolved
        validation = self._constraint_validator.validate(
            match.constraints,
            definition.constraints_schema,
            schema_version=definition.constraints_schema_version,
        )
        self._trace_logger.debug(
            "activity_constraints:validated",
            activity_type=definition.activity_type,
            validation_stage="situation_analysis",
            source=match.matcher_type,
            schema_version=validation.schema_version,
            valid=validation.valid,
            normalized_constraints=validation.normalized_constraints,
            error_paths=[error.path for error in validation.errors],
            error_codes=[error.code for error in validation.errors],
            applied_defaults=validation.applied_defaults,
            warnings=list(validation.warnings),
        )
        self._trace_logger.debug(
            "situation_evaluator:deterministic_match",
            matched=True,
            activity_type=definition.activity_type,
            operation=match.operation.value,
            confidence=match.confidence,
        )
        return SituationAnalysis(
            activity_candidate=definition.activity_type,
            operation=match.operation,
            goal=match.goal,
            constraints=dict(validation.normalized_constraints),
            speech_act=self._speech_act(context.user_text),
            confidence=match.confidence,
            reason=match.reason,
            evaluator_type="matcher",
            constraint_errors=validation.errors,
            constraints_schema_version=validation.schema_version,
            matcher_id=match.matcher_id,
            matcher_type=match.matcher_type,
            matcher_evidence=match.evidence,
        )

    def _non_execution(
        self, text: str, kind: UserRequestKind, reason: str
    ) -> SituationAnalysis | None:
        hypothetical = self._is_hypothetical(text)
        if (
            kind
            not in {
                UserRequestKind.KNOWLEDGE,
                UserRequestKind.PAST_EVENT,
                UserRequestKind.NEGATIVE,
            }
            and not hypothetical
        ):
            return None
        knowledge = kind == UserRequestKind.KNOWLEDGE
        past = kind == UserRequestKind.PAST_EVENT
        negated = kind == UserRequestKind.NEGATIVE
        operation: ActivityOperation | None = (
            ActivityOperation.EXPLAIN
            if knowledge
            and any(marker in text for marker in ("って何", "ルール", "教えて"))
            else ActivityOperation.DISCUSS
        )
        if negated or past:
            operation = None
        return SituationAnalysis(
            activity_candidate=None,
            operation=operation,
            goal="話題として会話する",
            speech_act=self._speech_act(text),
            negated=negated,
            hypothetical=hypothetical,
            past_reference=past,
            knowledge_question=knowledge,
            confidence=0.99,
            reason=reason,
        )

    @staticmethod
    def _is_negated_expression(text: str) -> bool:
        normalized = text.strip()
        return any(
            marker in normalized
            for marker in (
                "たくない",
                "しないで",
                "やめないで",
                "なくていい",
                "まだ続けたい",
            )
        )

    @staticmethod
    def _is_administrative_direction(text: str, kind: UserRequestKind) -> bool:
        if kind == UserRequestKind.EXECUTION:
            return True
        normalized = text.strip()
        return any(
            marker in normalized
            for marker in (
                "オープニング",
                "本題に入",
                "メインに入",
                "雑談を始め",
                "話題を変え",
                "次の話題",
                "締めに入",
                "エンディング",
            )
        )

    @staticmethod
    def _is_hypothetical(text: str) -> bool:
        return any(
            marker in text for marker in ("としたら", "とすれば", "仮に")
        ) or text.startswith("もし")

    @staticmethod
    def _speech_act(text: str) -> SpeechAct:
        normalized = text.strip()
        if any(
            marker in normalized for marker in ("しませんか", "しない？", "しようか")
        ):
            return SpeechAct.PROPOSAL
        if normalized.endswith(("？", "?")):
            return SpeechAct.QUESTION
        if normalized.endswith(("してください", "して", "付き合って")):
            return SpeechAct.REQUEST
        if normalized.endswith(("始めて", "やめて")):
            return SpeechAct.COMMAND
        return SpeechAct.STATEMENT
