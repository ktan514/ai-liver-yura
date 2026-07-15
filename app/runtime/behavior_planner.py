from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from app.core.plugins.user_request import UserRequestKind, interpret_user_request
from app.domain.activities import ActivityResult
from app.domain.activity_constraints import (
    ActivityConstraintValidator,
    ConstraintValidationResult,
)
from app.domain.autonomous_planning import (
    AutonomousSituationAnalysis,
    AutonomousSituationContext,
)
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    ActivityPlan,
    ActivityPlanEvaluation,
    BehaviorDecision,
    BehaviorPlanningContext,
    SituationAnalysis,
)
from app.ports.llm_roles import ResponseGeneratorRoleAdapter
from app.ports.response_generator import ResponseGenerator
from app.runtime.ongoing_input import (
    OngoingActivityTransitionPolicy,
    OngoingInputInterpreter,
)
from app.runtime.situation_evaluator import SituationEvaluator
from app.utils.trace import TraceLogger


class BehaviorPlanner:
    """客観的なSituation AnalysisをAgentの次の行動へ変換する。"""

    def __init__(
        self,
        response_generator: ResponseGenerator | None = None,
        *,
        situation_evaluator: SituationEvaluator | None = None,
        confidence_threshold: float = 0.85,
        max_semantic_attempts: int = 1,
        ongoing_input_interpreter: OngoingInputInterpreter | None = None,
        ongoing_transition_policy: OngoingActivityTransitionPolicy | None = None,
        constraint_validator: ActivityConstraintValidator | None = None,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold は0.0以上1.0以下で指定してください。")
        if max_semantic_attempts < 1:
            raise ValueError("max_semantic_attempts は1以上で指定してください。")
        if situation_evaluator is None:
            if response_generator is None:
                raise ValueError("situation_evaluator または response_generator が必要です。")
            situation_evaluator = SituationEvaluator(
                ResponseGeneratorRoleAdapter(response_generator),
                confidence_threshold=confidence_threshold,
                max_attempts=max_semantic_attempts,
            )
        self._situation_evaluator = situation_evaluator
        self._confidence_threshold = confidence_threshold
        self._ongoing_input_interpreter = ongoing_input_interpreter or OngoingInputInterpreter(
            confidence_threshold=confidence_threshold
        )
        self._ongoing_transition_policy = (
            ongoing_transition_policy or OngoingActivityTransitionPolicy()
        )
        self._constraint_validator = constraint_validator or ActivityConstraintValidator()
        self._trace_logger = TraceLogger()

    async def evaluate_situation(self, context: BehaviorPlanningContext) -> SituationAnalysis:
        """RuntimeCoordinator向けの明示的なSituation Evaluator境界。"""

        return await self._situation_evaluator.evaluate(context)

    def plan_autonomous(
        self,
        context: AutonomousSituationContext,
        analysis: AutonomousSituationAnalysis,
    ) -> ActivityPlan:
        """内的状態から発話本文を含まない自律Activity Planを確定する。"""

        energy = float(context.drive_state.get("energy", 0.0))
        talkativeness_value = context.emotion_state.get("talkativeness", 0.0)
        talkativeness = (
            float(talkativeness_value) if isinstance(talkativeness_value, (int, float)) else 0.0
        )
        if context.ongoing_activity is not None:
            decision = BehaviorDecision.WAIT
            activity_type = "wait"
            goal = "進行中Activityを優先して待機する"
            action = "wait"
        elif energy < 0.2 or talkativeness < 0.2:
            decision = BehaviorDecision.NO_ACTION
            activity_type = "no_action"
            goal = "発話せず内的状態の変化を待つ"
            action = "no_action"
        else:
            decision = BehaviorDecision.START_ACTIVITY
            activity_type = "autonomous_talk"
            action = analysis.suggested_action
            goal = f"{analysis.topic_candidate}について短く自律的に話す"
        plan = ActivityPlan(
            decision=decision,
            activity_type=activity_type,
            goal=goal,
            operation=ActivityOperation.START
            if decision == BehaviorDecision.START_ACTIVITY
            else None,
            constraints=dict(analysis.constraints),
            planner_constraints=(
                "発話本文を生成しない",
                "選択済みtopicを大幅に変更しない",
                "外部操作や検索を実行したと主張しない",
            ),
            confidence=1.0,
            reason=analysis.planning_reason,
            planner_type="autonomous_deterministic",
            topic=analysis.topic_candidate,
            planning_reason=analysis.planning_reason,
            autonomous_action=action,
        )
        self._trace_logger.info(
            "behavior_planner:autonomous_plan_decided",
            source_event_id=context.source_event_id,
            decision=plan.decision.value,
            autonomous_action=action,
            topic=plan.topic,
            planning_reason=plan.planning_reason,
        )
        self._trace_logger.debug(
            "behavior_planner:autonomous_plan_context",
            source_event_id=context.source_event_id,
            drive=context.drive_state,
            emotion=context.emotion_state,
            topic_state=context.topic_state,
            goal=plan.goal,
        )
        return plan

    async def plan(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis | None = None,
    ) -> ActivityPlan:
        """状況分析と現在状態からActivity Planを決定する。"""

        situation = analysis or await self.evaluate_situation(context)
        plan = self.plan_from_analysis(context, situation)
        self._trace_logger.debug(
            "behavior_planner:final_activity_plan",
            source=situation.evaluator_type,
            plan=plan,
        )
        return plan

    def plan_from_analysis(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> ActivityPlan:
        definition = self._resolve_definition(context, analysis.activity_candidate)
        if definition is not None:
            validation = self._constraint_validator.validate(
                analysis.constraints,
                definition.constraints_schema,
                schema_version=definition.constraints_schema_version,
            )
            if not validation.valid:
                self._trace_logger.info(
                    "activity_constraints:confirmation_required",
                    activity_type=definition.activity_type,
                    schema_version=definition.constraints_schema_version,
                    validation_stage="behavior_plan",
                    error_codes=[error.code for error in validation.errors],
                )
                return ActivityPlan(
                    decision=BehaviorDecision.ASK_CONFIRMATION,
                    activity_type=definition.activity_type,
                    goal="Activityの条件を確認する",
                    required_capability=definition.required_capability,
                    provider_plugin_id=definition.provider_plugin_id,
                    operation=analysis.operation,
                    constraints=dict(validation.normalized_constraints),
                    planner_constraints=("constraints検証完了前に実行しない",),
                    speech_act=analysis.speech_act,
                    confidence=analysis.confidence,
                    reason="activity_constraints_invalid",
                    planner_type=analysis.evaluator_type,
                    constraint_errors=validation.errors,
                    constraints_schema_version=validation.schema_version,
                )
            analysis = replace(
                analysis,
                constraints=dict(validation.normalized_constraints),
                constraint_errors=(),
                constraints_schema_version=validation.schema_version,
            )
        ongoing_interpretation = self._ongoing_input_interpreter.interpret(context, analysis)
        if ongoing_interpretation is not None:
            return self._ongoing_transition_policy.plan(
                context,
                analysis,
                ongoing_interpretation,
            )

        if analysis.evaluator_type == "llm" and analysis.confidence < self._confidence_threshold:
            return ActivityPlan(
                decision=BehaviorDecision.ASK_CONFIRMATION,
                activity_type=(
                    definition.activity_type
                    if definition is not None
                    else analysis.activity_candidate or "conversation"
                ),
                goal=analysis.goal or "意図を短く確認する",
                required_capability=(
                    definition.required_capability if definition is not None else None
                ),
                provider_plugin_id=(
                    definition.provider_plugin_id if definition is not None else None
                ),
                operation=analysis.operation,
                constraints=dict(analysis.constraints),
                planner_constraints=("低確信度のためActivityを実行しない",),
                speech_act=analysis.speech_act,
                confidence=analysis.confidence,
                reason="semantic_confidence_below_threshold",
                planner_type=analysis.evaluator_type,
                constraints_schema_version=analysis.constraints_schema_version,
            )

        if definition is not None and analysis.operation is not None:
            validation = self._constraint_validator.validate(
                analysis.constraints,
                definition.constraints_schema,
                schema_version=definition.constraints_schema_version,
            )
            decision = (
                BehaviorDecision.START_ACTIVITY
                if analysis.operation == ActivityOperation.START
                else BehaviorDecision.CONTINUE_ACTIVITY
            )
            return ActivityPlan(
                decision=decision,
                activity_type=definition.activity_type,
                goal=analysis.goal,
                required_capability=definition.required_capability,
                provider_plugin_id=definition.provider_plugin_id,
                operation=analysis.operation,
                constraints=dict(validation.normalized_constraints),
                planner_constraints=("Capability検証後にのみ実行する",),
                speech_act=analysis.speech_act,
                confidence=analysis.confidence,
                reason=analysis.reason,
                planner_type=analysis.evaluator_type,
                constraints_schema_version=validation.schema_version,
                validated_constraints=validation.as_validated(),
            )

        request = interpret_user_request(context.user_text)
        planner_constraints: tuple[str, ...] = ()
        reason = analysis.reason
        if request.kind == UserRequestKind.EXECUTION:
            planner_constraints = (
                "要求された行為を実行したふりをしない",
                "同じ実行Activityを再提案しない",
            )
            if analysis.evaluator_type == "fallback":
                reason = "execution_request_without_matching_activity"
        return ActivityPlan(
            decision=BehaviorDecision.CONVERSATION,
            activity_type="conversation",
            goal=analysis.goal,
            operation=analysis.operation,
            constraints=analysis.constraints,
            planner_constraints=planner_constraints,
            speech_act=analysis.speech_act,
            negated=analysis.negated,
            hypothetical=analysis.hypothetical,
            past_reference=analysis.past_reference,
            knowledge_question=analysis.knowledge_question,
            confidence=analysis.confidence,
            reason=reason,
            planner_type=analysis.evaluator_type,
        )

    def parse_llm_plan(
        self,
        raw: str,
        *,
        definitions: tuple[ActivityDefinition, ...] = (),
    ) -> ActivityPlan | None:
        """旧テスト・外部呼出し向け互換API。意味解析自体はEvaluatorへ委譲する。"""

        analysis = self._situation_evaluator.parse(raw, definitions)
        if analysis is None:
            return None
        return self.plan_from_analysis(
            BehaviorPlanningContext(
                user_text="",
                source_event_id="compatibility-parse",
                available_capabilities=frozenset(),
                activity_definitions=definitions,
            ),
            analysis,
        )

    def fallback_after_rejection(self, rejected: ActivityPlanEvaluation) -> ActivityPlan:
        """拒否Resultを受け、同一Activityを再提案せず会話へ遷移する。"""

        return ActivityPlan(
            decision=BehaviorDecision.CONVERSATION,
            activity_type="conversation",
            goal="実行できなかった要求へ自然な通常会話で応答する",
            operation=ActivityOperation.DISCUSS,
            planner_constraints=(
                "拒否されたActivityを再提案しない",
                "実行したふりをしない",
                "内部技術用語を発話しない",
            ),
            confidence=1.0,
            reason=f"fallback_after_{rejected.result.result_type}",
        )

    @staticmethod
    def _resolve_definition(
        context: BehaviorPlanningContext, activity_type: str | None
    ) -> ActivityDefinition | None:
        if activity_type is None:
            return None
        definition = next(
            (item for item in context.activity_definitions if item.activity_type == activity_type),
            None,
        )
        active = context.active_activity_definition
        if definition is None and active is not None and active.activity_type == activity_type:
            return active
        return definition


class ActivityPlanValidator:
    """Activity定義と現在のCapability Registryで実行前検証する。"""

    def __init__(
        self,
        capability_available: Callable[[str, str | None], bool],
        activity_definitions: Callable[[], tuple[ActivityDefinition, ...]] | None = None,
        constraint_validator: ActivityConstraintValidator | None = None,
    ) -> None:
        self._capability_available = capability_available
        self._activity_definitions = activity_definitions
        self._constraint_validator = constraint_validator or ActivityConstraintValidator()
        self._trace_logger = TraceLogger()

    def validate(self, plan: ActivityPlan) -> ActivityPlanEvaluation:
        if plan.required_capability is None:
            if plan.decision == BehaviorDecision.START_ACTIVITY:
                return self._reject(plan, "required_capability_missing")
            evaluation = ActivityPlanEvaluation(
                plan=plan,
                accepted=True,
                result=ActivityResult(
                    result_type="activity_plan_accepted",
                    summary="Capabilityを必要としないActivity Planを受理した",
                    data={"activity_type": plan.activity_type},
                ),
            )
            self._trace_evaluation(evaluation)
            return evaluation
        if plan.operation is None:
            return self._reject(plan, "semantic_operation_missing")
        definition: ActivityDefinition | None = None
        if self._activity_definitions is not None:
            definition = next(
                (
                    item
                    for item in self._activity_definitions()
                    if item.activity_type == plan.activity_type
                    and item.required_capability == plan.required_capability
                    and item.provider_plugin_id == plan.provider_plugin_id
                ),
                None,
            )
            if definition is None or plan.operation not in definition.supported_operations:
                return self._reject(plan, "activity_definition_not_found")
            if (
                plan.constraints_schema_version is not None
                and plan.constraints_schema_version != definition.constraints_schema_version
            ):
                self._trace_logger.info(
                    "activity_constraints:schema_version_mismatch",
                    activity_type=plan.activity_type,
                    planned_version=plan.constraints_schema_version,
                    current_version=definition.constraints_schema_version,
                )
                return self._reject(plan, "constraints_schema_version_mismatch")
            validation = self._constraint_validator.validate(
                plan.constraints,
                definition.constraints_schema,
                schema_version=definition.constraints_schema_version,
            )
            if not validation.valid:
                self._trace_logger.info(
                    "activity_constraints:validation_failed",
                    activity_type=plan.activity_type,
                    validation_stage="activity_plan",
                    schema_version=definition.constraints_schema_version,
                    errors=[error.code for error in validation.errors],
                )
                return self._reject(plan, "constraints_invalid")
            plan = replace(
                plan,
                constraints=dict(validation.normalized_constraints),
                constraint_errors=(),
                constraints_schema_version=validation.schema_version,
                validated_constraints=validation.as_validated(),
            )
        capability = plan.required_capability
        operation = plan.operation
        assert capability is not None and operation is not None
        if self._capability_available(capability, plan.provider_plugin_id):
            evaluation = ActivityPlanEvaluation(
                plan=plan,
                accepted=True,
                result=ActivityResult(
                    result_type="activity_plan_accepted",
                    summary="必要なCapabilityを確認した",
                    data={
                        "activity_type": plan.activity_type,
                        "required_capability": capability,
                        "operation": operation.value,
                    },
                ),
            )
            self._trace_evaluation(evaluation)
            return evaluation
        return self._reject(plan, "capability_unavailable")

    def validate_constraints(
        self,
        plan: ActivityPlan,
        constraints: dict[str, object] | None = None,
    ) -> ConstraintValidationResult | None:
        if self._activity_definitions is None:
            return None
        definition = next(
            (
                item
                for item in self._activity_definitions()
                if item.activity_type == plan.activity_type
                and item.provider_plugin_id == plan.provider_plugin_id
            ),
            None,
        )
        if definition is None:
            return None
        return self._constraint_validator.validate(
            constraints if constraints is not None else plan.constraints,
            definition.constraints_schema,
            schema_version=definition.constraints_schema_version,
        )

    def _reject(self, plan: ActivityPlan, reason: str) -> ActivityPlanEvaluation:
        evaluation = ActivityPlanEvaluation(
            plan=plan,
            accepted=False,
            fallback_required=True,
            result=ActivityResult(
                result_type="activity_plan_rejected",
                summary="現在利用できないためActivityを開始しなかった",
                succeeded=False,
                data={
                    "activity_type": plan.activity_type,
                    "required_capability": plan.required_capability,
                    "operation": plan.operation.value if plan.operation else None,
                    "reason": reason,
                },
            ),
        )
        self._trace_evaluation(evaluation)
        return evaluation

    def _trace_evaluation(self, evaluation: ActivityPlanEvaluation) -> None:
        self._trace_logger.debug(
            "behavior_planner:capability_validation",
            activity_type=evaluation.plan.activity_type,
            operation=evaluation.plan.operation.value if evaluation.plan.operation else None,
            required_capability=evaluation.plan.required_capability,
            provider_plugin_id=evaluation.plan.provider_plugin_id,
            accepted=evaluation.accepted,
            reason=evaluation.result.data.get("reason"),
        )
