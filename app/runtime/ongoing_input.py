from __future__ import annotations

from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
    OngoingInputDecision,
    OngoingInputInterpretation,
    SituationAnalysis,
)
from app.utils.trace import TraceLogger


class OngoingInputInterpreter:
    """Situation Analysisを、進行中Activityとの関係へ正規化する。"""

    def __init__(self, *, confidence_threshold: float = 0.85) -> None:
        self._confidence_threshold = confidence_threshold
        self._trace_logger = TraceLogger()

    def interpret(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> OngoingInputInterpretation | None:
        ongoing = context.ongoing_activity
        current_type = (
            ongoing.activity_type if ongoing is not None else context.ongoing_activity_type
        )
        if current_type is None and context.active_activity_definition is not None:
            current_type = context.active_activity_definition.activity_type
        if current_type is None:
            return None

        explicit = analysis.ongoing_input_decision
        if analysis.confidence < self._confidence_threshold:
            decision = OngoingInputDecision.ASK_CONFIRMATION
        elif explicit is not None:
            decision = explicit
        elif analysis.hypothetical or analysis.past_reference:
            decision = OngoingInputDecision.CONVERSATION_ABOUT_CURRENT
        elif analysis.negated:
            decision = (
                OngoingInputDecision.CONTINUE_CURRENT
                if analysis.activity_candidate in {None, current_type}
                else OngoingInputDecision.CONVERSATION_UNRELATED
            )
        elif analysis.knowledge_question:
            decision = OngoingInputDecision.CONVERSATION_ABOUT_CURRENT
        elif analysis.activity_candidate == current_type:
            if analysis.operation == ActivityOperation.STOP:
                decision = OngoingInputDecision.STOP_CURRENT
            elif analysis.operation in {ActivityOperation.EXPLAIN, ActivityOperation.DISCUSS}:
                decision = OngoingInputDecision.CONVERSATION_ABOUT_CURRENT
            else:
                decision = OngoingInputDecision.CONTINUE_CURRENT
        elif analysis.activity_candidate is not None:
            decision = OngoingInputDecision.START_OTHER_ACTIVITY
        elif analysis.operation in {ActivityOperation.EXPLAIN, ActivityOperation.DISCUSS}:
            decision = OngoingInputDecision.CONVERSATION_UNRELATED
        else:
            decision = OngoingInputDecision.ASK_CONFIRMATION

        interpretation = OngoingInputInterpretation(
            decision=decision,
            confidence=analysis.confidence,
            reason=analysis.reason,
            current_activity_type=current_type,
            requested_activity_type=(
                analysis.activity_candidate
                if analysis.activity_candidate not in {None, current_type}
                else None
            ),
        )
        self._trace_logger.info(
            "ongoing_input_interpreter:decision",
            ongoing_activity_id=(ongoing.ongoing_activity_id if ongoing is not None else None),
            current_activity_type=current_type,
            decision=decision.value,
            requested_activity_type=interpretation.requested_activity_type,
            confidence=analysis.confidence,
            reason=analysis.reason,
        )
        return interpretation


class OngoingActivityTransitionPolicy:
    """分類結果から状態変更を伴わないActivity Planを構築する。"""

    def __init__(self) -> None:
        self._trace_logger = TraceLogger()

    def plan(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
        interpretation: OngoingInputInterpretation,
    ) -> ActivityPlan:
        current = self._definition(context, interpretation.current_activity_type)
        target = self._definition(context, interpretation.requested_activity_type)
        decision = interpretation.decision

        if decision in {
            OngoingInputDecision.CONTINUE_CURRENT,
            OngoingInputDecision.RESUME_CURRENT,
        }:
            plan = self._current_plan(
                current,
                analysis,
                constraints=self._constraints(context, analysis),
                operation=ActivityOperation.CONTINUE,
                ongoing_decision=decision,
            )
        elif decision in {
            OngoingInputDecision.STOP_CURRENT,
            OngoingInputDecision.PAUSE_CURRENT,
        }:
            plan = self._current_plan(
                current,
                analysis,
                constraints=self._constraints(context, analysis),
                operation=(
                    ActivityOperation.STOP
                    if decision == OngoingInputDecision.STOP_CURRENT
                    else ActivityOperation.CONTINUE
                ),
                ongoing_decision=decision,
            )
        elif decision == OngoingInputDecision.SWITCH_ACTIVITY and target is not None:
            plan = ActivityPlan(
                decision=BehaviorDecision.SWITCH_ACTIVITY,
                activity_type=target.activity_type,
                goal=analysis.goal,
                required_capability=target.required_capability,
                provider_plugin_id=target.provider_plugin_id,
                operation=ActivityOperation.START,
                constraints=analysis.constraints,
                speech_act=analysis.speech_act,
                confidence=analysis.confidence,
                reason=analysis.reason,
                planner_type=analysis.evaluator_type,
                ongoing_input_decision=decision,
                current_activity_type=interpretation.current_activity_type,
                requested_new_activity=target.activity_type,
                current_activity_capability=(
                    current.required_capability if current is not None else None
                ),
                current_activity_provider_plugin_id=(
                    current.provider_plugin_id if current is not None else None
                ),
            )
        elif decision == OngoingInputDecision.START_OTHER_ACTIVITY:
            plan = ActivityPlan(
                decision=BehaviorDecision.ASK_CONFIRMATION,
                activity_type=(target.activity_type if target is not None else "conversation"),
                goal=analysis.goal,
                required_capability=(target.required_capability if target is not None else None),
                provider_plugin_id=(target.provider_plugin_id if target is not None else None),
                operation=ActivityOperation.START,
                constraints=analysis.constraints,
                planner_constraints=("確認前に現在Activityを変更しない",),
                speech_act=analysis.speech_act,
                confidence=analysis.confidence,
                reason=analysis.reason,
                planner_type=analysis.evaluator_type,
                ongoing_input_decision=decision,
                current_activity_type=interpretation.current_activity_type,
                current_activity_preserved=True,
                requested_new_activity=interpretation.requested_activity_type,
                current_activity_capability=(
                    current.required_capability if current is not None else None
                ),
                current_activity_provider_plugin_id=(
                    current.provider_plugin_id if current is not None else None
                ),
            )
        elif decision == OngoingInputDecision.ASK_CONFIRMATION:
            plan = ActivityPlan(
                decision=BehaviorDecision.ASK_CONFIRMATION,
                activity_type=(current.activity_type if current is not None else "conversation"),
                goal=analysis.goal or "進行中Activityをどう扱うか短く確認する",
                required_capability=(current.required_capability if current is not None else None),
                provider_plugin_id=(current.provider_plugin_id if current is not None else None),
                operation=analysis.operation,
                constraints=self._constraints(context, analysis),
                planner_constraints=("確認前に進行中Activityを変更しない",),
                speech_act=analysis.speech_act,
                confidence=analysis.confidence,
                reason=analysis.reason,
                planner_type=analysis.evaluator_type,
                ongoing_input_decision=decision,
                current_activity_type=interpretation.current_activity_type,
                current_activity_preserved=True,
                current_activity_capability=(
                    current.required_capability if current is not None else None
                ),
                current_activity_provider_plugin_id=(
                    current.provider_plugin_id if current is not None else None
                ),
            )
        elif decision == OngoingInputDecision.NO_ACTION:
            plan = self._conversation_plan(
                analysis,
                interpretation,
                decision=BehaviorDecision.NO_ACTION,
                goal="状態を変更せず待機する",
            )
        else:
            plan = self._conversation_plan(
                analysis,
                interpretation,
                decision=BehaviorDecision.CONVERSATION,
                goal=analysis.goal,
            )

        self._trace_logger.info(
            "ongoing_activity_transition_policy:selected",
            ongoing_input_decision=decision.value,
            behavior_decision=plan.decision.value,
            current_activity_type=interpretation.current_activity_type,
            requested_new_activity=plan.requested_new_activity,
            current_activity_preserved=plan.current_activity_preserved,
            current_activity_paused=plan.current_activity_paused,
        )
        return plan

    @staticmethod
    def _definition(
        context: BehaviorPlanningContext,
        activity_type: str | None,
    ) -> ActivityDefinition | None:
        if activity_type is None:
            return None
        if (
            context.active_activity_definition is not None
            and context.active_activity_definition.activity_type == activity_type
        ):
            return context.active_activity_definition
        return next(
            (item for item in context.activity_definitions if item.activity_type == activity_type),
            None,
        )

    @staticmethod
    def _current_plan(
        definition: ActivityDefinition | None,
        analysis: SituationAnalysis,
        *,
        constraints: dict[str, object],
        operation: ActivityOperation,
        ongoing_decision: OngoingInputDecision,
    ) -> ActivityPlan:
        activity_type = definition.activity_type if definition is not None else "unknown"
        return ActivityPlan(
            decision=BehaviorDecision.CONTINUE_ACTIVITY,
            activity_type=activity_type,
            goal=analysis.goal,
            required_capability=(definition.required_capability if definition else None),
            provider_plugin_id=(definition.provider_plugin_id if definition else None),
            operation=operation,
            constraints=constraints,
            planner_constraints=("Capability検証後にのみ実行する",),
            speech_act=analysis.speech_act,
            confidence=analysis.confidence,
            reason=analysis.reason,
            planner_type=analysis.evaluator_type,
            ongoing_input_decision=ongoing_decision,
            current_activity_type=activity_type,
            current_activity_preserved=operation != ActivityOperation.STOP,
            current_activity_paused=(ongoing_decision == OngoingInputDecision.PAUSE_CURRENT),
            current_activity_capability=(definition.required_capability if definition else None),
            current_activity_provider_plugin_id=(
                definition.provider_plugin_id if definition else None
            ),
        )

    @staticmethod
    def _constraints(
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> dict[str, object]:
        if analysis.constraints:
            return dict(analysis.constraints)
        if context.ongoing_activity is not None:
            return dict(context.ongoing_activity.constraints)
        return {}

    @staticmethod
    def _conversation_plan(
        analysis: SituationAnalysis,
        interpretation: OngoingInputInterpretation,
        *,
        decision: BehaviorDecision,
        goal: str,
    ) -> ActivityPlan:
        return ActivityPlan(
            decision=decision,
            activity_type="conversation",
            goal=goal,
            operation=ActivityOperation.DISCUSS,
            constraints=analysis.constraints,
            planner_constraints=("進行中Activityの状態を暗黙に変更しない",),
            speech_act=analysis.speech_act,
            negated=analysis.negated,
            hypothetical=analysis.hypothetical,
            past_reference=analysis.past_reference,
            knowledge_question=analysis.knowledge_question,
            confidence=analysis.confidence,
            reason=analysis.reason,
            planner_type=analysis.evaluator_type,
            ongoing_input_decision=interpretation.decision,
            current_activity_type=interpretation.current_activity_type,
            current_activity_preserved=True,
            requested_new_activity=interpretation.requested_activity_type,
        )
