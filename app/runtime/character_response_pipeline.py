from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.domain.activities import (
    Activity,
    ActivityStatus,
    ActivityType,
    OngoingActivity,
)
from app.domain.activity_turn_result import (
    CharacterGenerationResult,
    CharacterGenerationStatus,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
    CharacterResponse,
    Claim,
    ClaimType,
    OngoingActivityContext,
    ReactionPlan,
    ReactionSegment,
    ResponseClaim,
    ResponseContext,
    ResponseValidationResult,
    VoiceIntent,
)
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicHistory
from app.domain.trace_context import trace_context_from
from app.ports.llm_roles import CharacterModel, ResponseValidationModel
from app.ports.prompt_builder import (
    CharacterRolePromptBuilder,
    ResponseValidationPromptBuilder,
)
from app.runtime.response_claim_validator import (
    DeterministicFactValidator,
    IndependentClaimExtractor,
)
from app.utils.llm_trace import build_llm_trace_context
from app.utils.trace import TraceLogger


class ResponseContextBuilder:
    """Activityの実行事実をCharacter LLMへ渡せる最小文脈へ変換する。"""

    def __init__(
        self,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
    ) -> None:
        self._short_term_memory = short_term_memory
        self._topic_history = topic_history
        self._trace_logger = TraceLogger()

    def build(self, activity: Activity) -> ResponseContext:
        payload = activity.context.get("event_payload")
        event_payload = payload if isinstance(payload, dict) else {}
        result_value = event_payload.get(
            "activity_execution_result",
            activity.context.get("activity_execution_result"),
        )
        result = (
            result_value
            if isinstance(result_value, ActivityExecutionResult)
            else self._infer_result(activity, event_payload)
        )
        ongoing_activity = self._ongoing_context(
            activity.context.get("ongoing_activity")
        )
        transition_value = event_payload.get(
            "ongoing_transition", activity.context.get("ongoing_transition")
        )
        transition = transition_value if isinstance(transition_value, dict) else {}
        behavior_plan_value = event_payload.get(
            "behavior_plan", activity.context.get("behavior_plan")
        )
        behavior_plan = (
            behavior_plan_value if isinstance(behavior_plan_value, dict) else {}
        )
        situation_value = event_payload.get(
            "autonomous_situation_context",
            activity.context.get("autonomous_situation_context"),
        )
        situation = situation_value if isinstance(situation_value, dict) else {}
        analysis_value = event_payload.get(
            "autonomous_situation_analysis",
            activity.context.get("autonomous_situation_analysis"),
        )
        autonomous_analysis = analysis_value if isinstance(analysis_value, dict) else {}
        confirmation_value = event_payload.get("pending_confirmation")
        confirmation = (
            confirmation_value if isinstance(confirmation_value, dict) else {}
        )
        allowed, forbidden = self._claims_for(
            result.status,
            activity_type=result.activity_type,
            operation=result.operation,
            ongoing=ongoing_activity is not None
            and ongoing_activity.ongoing_status
            in {ActivityStatus.ACTIVE.value, ActivityStatus.WAITING.value},
        )
        context = ResponseContext(
            user_input=str(
                event_payload.get("text") or event_payload.get("comment") or ""
            ),
            activity_type=result.activity_type,
            operation=result.operation,
            status=result.status,
            failure_reason=result.failure_reason,
            result_summary=str(result.payload.get("summary") or ""),
            allowed_claims=allowed,
            forbidden_claims=forbidden,
            activity_goal=activity.goal,
            input_authority_role=str(
                activity.context.get("input_authority", {}).get("role", "user")
                if isinstance(activity.context.get("input_authority"), dict)
                else "user"
            ),
            instruction_trusted=bool(
                activity.context.get("input_authority", {}).get(
                    "instruction_trusted", False
                )
                if isinstance(activity.context.get("input_authority"), dict)
                else False
            ),
            emotion=(
                dict(activity.context.get("emotion", {}))
                if isinstance(activity.context.get("emotion"), dict)
                else {}
            ),
            relationship=(
                dict(event_payload.get("relationship", {}))
                if isinstance(event_payload.get("relationship"), dict)
                else (
                    dict(situation.get("relationship_state", {}))
                    if isinstance(situation.get("relationship_state"), dict)
                    else {}
                )
            ),
            situation=(
                dict(event_payload.get("situation", {}))
                if isinstance(event_payload.get("situation"), dict)
                else {}
            ),
            memory=(
                dict(event_payload.get("memory", {}))
                if isinstance(event_payload.get("memory"), dict)
                else {}
            ),
            ongoing_activity=ongoing_activity,
            ongoing_input_decision=self._optional_str(
                transition.get("ongoing_input_decision")
            ),
            current_activity_status=self._optional_str(
                transition.get("current_activity_status")
            ),
            current_activity_preserved=bool(
                transition.get("current_activity_preserved", False)
            ),
            current_activity_paused=bool(
                transition.get("current_activity_paused", False)
            ),
            current_activity_stopped=bool(
                transition.get("current_activity_stopped", False)
            ),
            requested_new_activity=self._optional_str(
                transition.get("requested_new_activity")
            ),
            transition_result=self._optional_str(transition.get("transition_result")),
            topic=self._optional_str(
                result.payload.get("selected_topic") or behavior_plan.get("topic")
            ),
            planning_reason=self._optional_str(
                result.payload.get("planning_reason")
                or behavior_plan.get("planning_reason")
            ),
            constraints=dict(result.constraints),
            drive={
                str(key): float(value)
                for key, value in (
                    situation.get("drive_state", {}).items()
                    if isinstance(situation.get("drive_state"), dict)
                    else ()
                )
                if isinstance(value, (int, float))
            },
            recent_speech_summary=(
                str(situation.get("recent_speech_summary") or "")
                or self._short_term_memory.build_recent_speech_summary(limit=3)
                if self._short_term_memory is not None
                else str(situation.get("recent_speech_summary") or "")
            ),
            recent_conversation_summary=(
                self._short_term_memory.build_recent_conversation_summary(limit=6)
                if self._short_term_memory is not None
                else ""
            ),
            recent_topic_summary=(
                str(situation.get("recent_topic_summary") or "")
                or "\n".join(
                    entry.summary
                    for entry in self._topic_history.recent_entries(limit=3)
                )
                if self._topic_history is not None
                else str(situation.get("recent_topic_summary") or "")
            ),
            interrupted_topic_relation=self._optional_str(
                autonomous_analysis.get("relation_to_interrupted_topic")
            ),
            stream_status=self._optional_str(situation.get("stream_status")),
            confirmation_id=self._optional_str(confirmation.get("confirmation_id")),
            confirmation_type=self._optional_str(confirmation.get("confirmation_type")),
            confirmation_candidate_activity_type=self._optional_str(
                confirmation.get("candidate_activity_type")
            ),
            confirmation_candidate_operation=self._optional_str(
                confirmation.get("candidate_operation")
            ),
            confirmation_question=self._optional_str(confirmation.get("question")),
            confirmation_resolution=self._optional_str(confirmation.get("resolution")),
        )
        self._trace_logger.debug(
            "response_context_builder:built",
            source_activity_id=activity.activity_id,
            activity_type=context.activity_type,
            operation=context.operation,
            execution_status=context.status.value,
            allowed_claims=[claim.value for claim in context.allowed_claims],
            forbidden_claims=[claim.value for claim in context.forbidden_claims],
            has_failure=context.failure_reason is not None,
        )
        return context

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _ongoing_context(value: object) -> OngoingActivityContext | None:
        if not isinstance(value, OngoingActivity):
            return None
        summary_keys = (
            "plugin_id",
            "capability",
            "plugin_session_id",
            "plugin_state_version",
            "plugin_activity_status",
        )
        constraints_value = value.context.get("constraints")
        constraints = (
            dict(constraints_value) if isinstance(constraints_value, dict) else {}
        )
        previous_output = (
            value.turns[-1].turn_result.output_result
            if value.turns
            and value.turns[-1].turn_result is not None
            and value.turns[-1].turn_result.output_result is not None
            else None
        )
        previous_output_status = (
            previous_output.status.value if previous_output is not None else None
        )
        previous_output_summary = None
        if previous_output_status == "partially_completed":
            previous_output_summary = "前回は処理後の案内を一部の方法で伝えられなかった"
        elif previous_output_status == "failed":
            previous_output_summary = "前回は処理後の案内を伝えられなかった"
        elif previous_output_status == "canceled":
            previous_output_summary = "前回の案内は途中で取り消された"
        return OngoingActivityContext(
            ongoing_activity_id=value.ongoing_activity_id,
            ongoing_activity_type=value.activity_type,
            ongoing_status=value.status.value,
            goal=value.goal,
            expected_input=value.expected_input,
            turn_count=len(value.turns),
            constraints=constraints,
            plugin_context_summary={
                key: value.context[key] for key in summary_keys if key in value.context
            },
            previous_output_status=previous_output_status,
            previous_output_summary=previous_output_summary,
        )

    @staticmethod
    def _infer_result(
        activity: Activity, payload: dict[str, Any]
    ) -> ActivityExecutionResult:
        rejected = bool(payload.get("execution_request_unmatched"))
        plan = payload.get("behavior_plan")
        plan_data = plan if isinstance(plan, dict) else {}
        status = (
            ActivityExecutionStatus.REJECTED
            if rejected
            else ActivityExecutionStatus.WAITING_INPUT
        )
        return ActivityExecutionResult(
            activity_type=str(
                plan_data.get("activity_type") or activity.activity_type.value
            ),
            operation=(
                str(plan_data.get("operation"))
                if plan_data.get("operation") is not None
                else None
            ),
            status=status,
            capability=(
                str(plan_data.get("required_capability"))
                if plan_data.get("required_capability") is not None
                else None
            ),
            provider=(
                str(plan_data.get("provider_plugin_id"))
                if plan_data.get("provider_plugin_id") is not None
                else None
            ),
            payload={
                "summary": (
                    "Activityを開始できなかった" if rejected else "会話を継続する"
                )
            },
            failure_reason=(
                str(payload.get("execution_match_reason")) if rejected else None
            ),
            constraints=(
                dict(plan_data.get("constraints", {}))
                if isinstance(plan_data.get("constraints"), dict)
                else {}
            ),
        )

    @staticmethod
    def _claims_for(
        status: ActivityExecutionStatus,
        *,
        activity_type: str,
        operation: str | None,
        ongoing: bool,
    ) -> tuple[tuple[ResponseClaim, ...], tuple[ResponseClaim, ...]]:
        if activity_type == "confirmation":
            return (
                (ResponseClaim.CONVERSATION_ONLY,),
                (
                    ResponseClaim.ACTIVITY_STARTED,
                    ResponseClaim.ACTIVITY_RUNNING,
                    ResponseClaim.ACTIVITY_CONTINUED,
                    ResponseClaim.ACTIVITY_COMPLETED,
                    ResponseClaim.ACTIVITY_SUCCEEDED,
                    ResponseClaim.EXTERNAL_RESULT_OBTAINED,
                    ResponseClaim.CAPABILITY_AVAILABLE,
                ),
            )
        if activity_type == ActivityType.AUTONOMOUS_TALK.value:
            return (
                (ResponseClaim.CONVERSATION_ONLY,),
                (
                    ResponseClaim.ACTIVITY_STARTED,
                    ResponseClaim.ACTIVITY_RUNNING,
                    ResponseClaim.ACTIVITY_CONTINUED,
                    ResponseClaim.ACTIVITY_COMPLETED,
                    ResponseClaim.ACTIVITY_SUCCEEDED,
                    ResponseClaim.ACTIVITY_FAILED,
                    ResponseClaim.ACTIVITY_REJECTED,
                    ResponseClaim.ACTIVITY_CANCELED,
                    ResponseClaim.EXTERNAL_RESULT_OBTAINED,
                    ResponseClaim.CAPABILITY_AVAILABLE,
                    ResponseClaim.CAPABILITY_UNAVAILABLE,
                    ResponseClaim.ACTIVITY_CONTINUES,
                    ResponseClaim.EXECUTION_UNAVAILABLE,
                ),
            )
        if status == ActivityExecutionStatus.REJECTED:
            return (
                (
                    ResponseClaim.ACTIVITY_REJECTED,
                    ResponseClaim.CAPABILITY_UNAVAILABLE,
                    ResponseClaim.EXECUTION_UNAVAILABLE,
                    ResponseClaim.CONVERSATION_ONLY,
                ),
                (
                    ResponseClaim.ACTIVITY_STARTED,
                    ResponseClaim.ACTIVITY_RUNNING,
                    ResponseClaim.ACTIVITY_CONTINUED,
                    ResponseClaim.ACTIVITY_COMPLETED,
                    ResponseClaim.ACTIVITY_SUCCEEDED,
                    ResponseClaim.ACTIVITY_CONTINUES,
                    ResponseClaim.EXTERNAL_RESULT_OBTAINED,
                ),
            )
        if status == ActivityExecutionStatus.SUCCEEDED:
            allowed = [
                ResponseClaim.ACTIVITY_COMPLETED,
                ResponseClaim.ACTIVITY_SUCCEEDED,
                ResponseClaim.EXTERNAL_RESULT_OBTAINED,
            ]
            if operation == "start":
                allowed.append(ResponseClaim.ACTIVITY_STARTED)
            if ongoing:
                allowed.extend(
                    (
                        ResponseClaim.ACTIVITY_RUNNING,
                        ResponseClaim.ACTIVITY_CONTINUED,
                        ResponseClaim.ACTIVITY_CONTINUES,
                    )
                )
            return (
                tuple(allowed),
                (
                    ResponseClaim.ACTIVITY_FAILED,
                    ResponseClaim.ACTIVITY_REJECTED,
                    ResponseClaim.ACTIVITY_CANCELED,
                    ResponseClaim.CAPABILITY_UNAVAILABLE,
                    ResponseClaim.EXECUTION_UNAVAILABLE,
                ),
            )
        if status == ActivityExecutionStatus.FAILED:
            return (
                (
                    ResponseClaim.ACTIVITY_FAILED,
                    ResponseClaim.CAPABILITY_UNAVAILABLE,
                    ResponseClaim.EXECUTION_UNAVAILABLE,
                    ResponseClaim.CONVERSATION_ONLY,
                ),
                (
                    ResponseClaim.ACTIVITY_STARTED,
                    ResponseClaim.ACTIVITY_RUNNING,
                    ResponseClaim.ACTIVITY_CONTINUED,
                    ResponseClaim.ACTIVITY_COMPLETED,
                    ResponseClaim.ACTIVITY_SUCCEEDED,
                    ResponseClaim.ACTIVITY_CONTINUES,
                    ResponseClaim.EXTERNAL_RESULT_OBTAINED,
                ),
            )
        if status == ActivityExecutionStatus.CANCELED:
            return (
                (
                    ResponseClaim.ACTIVITY_CANCELED,
                    ResponseClaim.CAPABILITY_UNAVAILABLE,
                    ResponseClaim.EXECUTION_UNAVAILABLE,
                    ResponseClaim.CONVERSATION_ONLY,
                ),
                (
                    ResponseClaim.ACTIVITY_RUNNING,
                    ResponseClaim.ACTIVITY_CONTINUED,
                    ResponseClaim.ACTIVITY_COMPLETED,
                    ResponseClaim.ACTIVITY_SUCCEEDED,
                    ResponseClaim.ACTIVITY_CONTINUES,
                    ResponseClaim.EXTERNAL_RESULT_OBTAINED,
                ),
            )
        allowed = [ResponseClaim.ACTIVITY_REQUESTED, ResponseClaim.CONVERSATION_ONLY]
        if ongoing:
            allowed.extend(
                (
                    ResponseClaim.ACTIVITY_RUNNING,
                    ResponseClaim.ACTIVITY_CONTINUED,
                    ResponseClaim.ACTIVITY_CONTINUES,
                )
            )
            if operation == "start":
                allowed.append(ResponseClaim.ACTIVITY_STARTED)
        return (
            tuple(allowed),
            (
                ResponseClaim.ACTIVITY_COMPLETED,
                ResponseClaim.ACTIVITY_SUCCEEDED,
                ResponseClaim.EXTERNAL_RESULT_OBTAINED,
            ),
        )


class CharacterLlmService:
    """確定済みResponseContextをキャラクター表現へ変換する。"""

    def __init__(
        self,
        model: CharacterModel,
        prompt_builder: CharacterRolePromptBuilder,
        character_profile: CharacterProfile | None = None,
    ) -> None:
        self._model = model
        self._character_profile = character_profile
        self._prompt_builder = prompt_builder
        self._trace_logger = TraceLogger()

    async def generate(
        self,
        source: Activity,
        context: ResponseContext,
        *,
        correction: str | None = None,
        attempt: int = 1,
    ) -> CharacterResponse:
        prompt = self._prompt_builder.build(
            context,
            character_profile=self._character_profile,
            correction=correction,
        )
        activity = Activity(
            activity_type=source.activity_type,
            goal="確定済み事実をキャラクターらしく表現する",
            source_event_id=source.source_event_id,
            context={
                "plugin_prompt_override": prompt,
                "llm_role": "character",
                "event_id": source.context.get("event_id"),
                "user_input": context.user_input,
                "response_context": asdict(context),
                "event_payload": {"text": context.user_input},
                "prepared_response_text": source.context.get("prepared_response_text"),
                "trace_context": source.context.get("trace_context"),
                "activity_turn_id": source.context.get("activity_turn_id"),
                "ongoing_activity": source.context.get("ongoing_activity"),
                "llm_attempt": attempt,
                "activity_execution_result": source.context.get(
                    "activity_execution_result"
                ),
            },
        )
        raw = await self._model.generate_character_response(activity)
        response = self.parse(raw)
        if response is None:
            raise ValueError("Character LLMの構造化応答が不正です。")
        trace = build_llm_trace_context(activity)
        self._trace_logger.info(
            "character_llm:response_generated",
            **trace.trace_context.as_log_fields(),
            llm_role="character",
            request_id=trace.request_id,
            attempt=attempt,
            source_activity_id=source.activity_id,
            speech_length=len(response.speech),
            expression=response.expression,
            has_gesture=response.gesture is not None,
            claims=[claim.value for claim in response.claims],
        )
        return response

    @staticmethod
    def parse(raw: str) -> CharacterResponse | None:
        try:
            value: Any = json.loads(raw.strip())
        except json.JSONDecodeError:
            return None
        if not isinstance(value, dict):
            return None
        parsed_claims = CharacterLlmService._parse_claims(value.get("claims", []))
        if parsed_claims is None:
            return None
        claims, claim_details = parsed_claims
        voice_intent = CharacterLlmService._parse_voice_intent(
            value.get("voice_intent")
        )
        if voice_intent is None:
            return None
        expression = str(value.get("expression") or "smile")
        gesture = str(value["gesture"]) if value.get("gesture") is not None else None
        reaction_plan = CharacterLlmService._parse_reaction_plan(
            value.get("reaction_segments"),
            default_expression=expression,
            default_voice_intent=voice_intent,
        )
        if value.get("reaction_segments") is not None and reaction_plan is None:
            return None
        speech_value = value.get("speech")
        speech = str(speech_value).strip() if isinstance(speech_value, str) else ""
        if reaction_plan is not None:
            speech = reaction_plan.speech
            first = reaction_plan.segments[0]
            expression = first.expression
            gesture = first.gesture
            voice_intent = first.voice_intent
        if not speech:
            return None
        return CharacterResponse(
            speech=speech,
            expression=expression,
            gesture=gesture,
            voice_intent=voice_intent,
            claims=claims,
            claim_details=claim_details,
            reaction_plan=reaction_plan,
        )

    @staticmethod
    def _parse_voice_intent(value: object) -> VoiceIntent | None:
        if value is None:
            return VoiceIntent()
        if (
            isinstance(value, dict)
            and isinstance(value.get("style"), str)
            and value["style"].strip()
        ):
            return VoiceIntent(style=value["style"].strip())
        return None

    @staticmethod
    def _parse_reaction_plan(
        value: object,
        *,
        default_expression: str,
        default_voice_intent: VoiceIntent,
    ) -> ReactionPlan | None:
        if value is None:
            return None
        if not isinstance(value, list) or not 1 <= len(value) <= 8:
            return None
        segments: list[ReactionSegment] = []
        for item in value:
            if not isinstance(item, dict):
                return None
            speech = item.get("speech")
            if not isinstance(speech, str) or not speech.strip():
                return None
            voice_intent = CharacterLlmService._parse_voice_intent(
                item.get("voice_intent", {"style": default_voice_intent.style})
            )
            pause = item.get("pause_after_seconds", 0.0)
            if (
                voice_intent is None
                or not isinstance(pause, (int, float))
                or isinstance(pause, bool)
            ):
                return None
            try:
                segment = ReactionSegment(
                    speech=speech.strip(),
                    expression=str(item.get("expression") or default_expression),
                    gesture=(
                        str(item["gesture"])
                        if item.get("gesture") is not None
                        else None
                    ),
                    voice_intent=voice_intent,
                    pause_after_seconds=float(pause),
                )
            except ValueError:
                return None
            segments.append(segment)
        return ReactionPlan(tuple(segments))

    @staticmethod
    def _parse_claims(
        value: object,
    ) -> tuple[tuple[ResponseClaim, ...], tuple[Claim, ...]] | None:
        if not isinstance(value, list):
            return None
        claims: list[ResponseClaim] = []
        details: list[Claim] = []
        for item in value:
            if isinstance(item, str):
                try:
                    claims.append(ResponseClaim(item))
                except ValueError:
                    return None
                continue
            if not isinstance(item, dict):
                return None
            try:
                claim_type = ClaimType(str(item["claim_type"]))
                response_claim = ResponseClaim(claim_type.value)
                status = (
                    ActivityExecutionStatus(str(item["status"]))
                    if item.get("status") is not None
                    else None
                )
                confidence = float(item.get("confidence", 1.0))
            except (KeyError, TypeError, ValueError):
                return None
            if not 0.0 <= confidence <= 1.0:
                return None
            claims.append(response_claim)
            details.append(
                Claim(
                    claim_type=claim_type,
                    activity_type=(
                        str(item["activity_type"])
                        if item.get("activity_type") is not None
                        else None
                    ),
                    operation=(
                        str(item["operation"])
                        if item.get("operation") is not None
                        else None
                    ),
                    status=status,
                    target=(
                        str(item["target"]) if item.get("target") is not None else None
                    ),
                    confidence=confidence,
                    evidence=str(item.get("evidence") or ""),
                )
            )
        return tuple(claims), tuple(details)


class ResponseValidator:
    """発話内容の主張をActivity実行事実と照合する。"""

    def __init__(
        self,
        model: ResponseValidationModel | None = None,
        prompt_builder: ResponseValidationPromptBuilder | None = None,
        claim_extractor: IndependentClaimExtractor | None = None,
        fact_validator: DeterministicFactValidator | None = None,
    ) -> None:
        self._model = model
        if model is not None and prompt_builder is None:
            raise ValueError("modelを使用する場合はprompt_builderが必要です。")
        self._prompt_builder = prompt_builder
        self._claim_extractor = claim_extractor or IndependentClaimExtractor()
        self._fact_validator = fact_validator or DeterministicFactValidator()
        self._trace_logger = TraceLogger()

    async def validate(
        self,
        source: Activity,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        attempt: int = 1,
    ) -> ResponseValidationResult:
        try:
            extracted_claims = self._claim_extractor.extract(context, response.speech)
        except Exception as error:
            result = ResponseValidationResult(False, "claim_extractor_failed")
            self._trace_logger.warning(
                "response_claim_extractor:failed",
                source_activity_id=source.activity_id,
                error_type=type(error).__name__,
            )
            self._trace_result(source, result)
            return result
        trace = build_llm_trace_context(source).trace_context
        self._trace_logger.debug(
            "response_claim_extractor:completed",
            **trace.as_log_fields(),
            component_role="claim_extractor",
            self_reported_claims=[claim.value for claim in response.claims],
            extracted_claim_types=[
                claim.claim_type.value for claim in extracted_claims
            ],
            attempt=attempt,
        )
        deterministic = self._fact_validator.validate(
            context, response, extracted_claims
        )
        if not deterministic.accepted:
            self._trace_result(source, deterministic)
            return deterministic
        if self._model is None:
            result = ResponseValidationResult(
                True,
                "deterministic_facts_valid",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result
        activity = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal="Character Responseと実行事実の整合性を評価する",
            source_event_id=source.source_event_id,
            context={
                "plugin_prompt_override": self._require_prompt_builder().build(
                    context,
                    response,
                    extracted_claims=extracted_claims,
                ),
                "llm_role": "response_validator",
                "response_context": asdict(context),
                "character_response": asdict(response),
                "trace_context": source.context.get("trace_context"),
                "activity_turn_id": source.context.get("activity_turn_id"),
                "ongoing_activity": source.context.get("ongoing_activity"),
                "llm_attempt": attempt,
                "activity_execution_result": source.context.get(
                    "activity_execution_result"
                ),
            },
        )
        try:
            raw = await self._model.validate_character_response(activity)
            value = json.loads(raw)
        except (Exception, json.JSONDecodeError):
            result = ResponseValidationResult(
                False,
                "validator_model_failed",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result
        if not isinstance(value, dict) or not isinstance(value.get("accepted"), bool):
            result = ResponseValidationResult(
                False,
                "validator_schema_invalid",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result
        objective_claims = self._parse_objective_claims(
            value.get("extracted_claims", [])
        )
        if objective_claims is None:
            result = ResponseValidationResult(
                False,
                "validator_schema_invalid",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result
        merged_claims = tuple(
            {
                (
                    claim.claim_type,
                    claim.activity_type,
                    claim.operation,
                    claim.status,
                    claim.target,
                    claim.evidence,
                ): claim
                for claim in (*extracted_claims, *objective_claims)
            }.values()
        )
        objective_facts = self._fact_validator.validate(
            context, response, merged_claims
        )
        if not objective_facts.accepted:
            self._trace_result(source, objective_facts)
            return objective_facts
        result = ResponseValidationResult(
            accepted=bool(value["accepted"]),
            reason=str(value.get("reason") or "objective_validation"),
            extracted_claims=merged_claims,
        )
        self._trace_result(source, result)
        return result

    def _require_prompt_builder(self) -> ResponseValidationPromptBuilder:
        if self._prompt_builder is None:
            raise RuntimeError(
                "Response Validation Prompt Builderが構成されていません。"
            )
        return self._prompt_builder

    @staticmethod
    def _parse_objective_claims(value: object) -> tuple[Claim, ...] | None:
        if not isinstance(value, list):
            return None
        claims: list[Claim] = []
        for item in value:
            if not isinstance(item, dict):
                return None
            try:
                claim_type = ClaimType(str(item["claim_type"]))
                status = (
                    ActivityExecutionStatus(str(item["status"]))
                    if item.get("status") is not None
                    else None
                )
                confidence = float(item.get("confidence", 1.0))
            except (KeyError, TypeError, ValueError):
                return None
            if not 0.0 <= confidence <= 1.0:
                return None
            claims.append(
                Claim(
                    claim_type=claim_type,
                    activity_type=(
                        str(item["activity_type"])
                        if item.get("activity_type") is not None
                        else None
                    ),
                    operation=(
                        str(item["operation"])
                        if item.get("operation") is not None
                        else None
                    ),
                    status=status,
                    target=(
                        str(item["target"]) if item.get("target") is not None else None
                    ),
                    confidence=confidence,
                    evidence=str(item.get("evidence") or ""),
                )
            )
        return tuple(claims)

    def _trace_result(self, source: Activity, result: ResponseValidationResult) -> None:
        trace = build_llm_trace_context(source)
        fields = {
            **trace.trace_context.as_log_fields(),
            "llm_role": "response_validator" if self._model is not None else None,
            "component_role": "response_validator",
            "source_activity_id": source.activity_id,
            "accepted": result.accepted,
            "reason": result.reason,
            "invalid_claims": [claim.value for claim in result.invalid_claims],
            "extracted_claims": [asdict(claim) for claim in result.extracted_claims],
            "claim_differences": list(result.claim_differences),
        }
        if result.accepted:
            self._trace_logger.debug("response_validator:accepted", **fields)
        else:
            self._trace_logger.warning("response_validator:rejected", **fields)


class CharacterResponsePipeline:
    def __init__(
        self,
        context_builder: ResponseContextBuilder,
        character_llm: CharacterLlmService,
        validator: ResponseValidator,
    ) -> None:
        self._context_builder = context_builder
        self._character_llm = character_llm
        self._validator = validator
        self._trace_logger = TraceLogger()

    async def generate(self, activity: Activity) -> CharacterResponse:
        response, _ = await self.generate_with_result(activity)
        return response

    async def generate_with_result(
        self, activity: Activity
    ) -> tuple[CharacterResponse, CharacterGenerationResult]:
        started_at = datetime.now(timezone.utc)
        activity_turn_id, ongoing_activity_id = self._correlation_ids(activity)
        trace = build_llm_trace_context(activity).trace_context
        context = self._context_builder.build(activity)
        validation: ResponseValidationResult | None = None
        last_error: str | None = None
        for attempt in range(2):
            try:
                response = await self._character_llm.generate(
                    activity,
                    context,
                    correction=(
                        self._correction(validation, context)
                        if validation is not None
                        else None
                    ),
                    attempt=attempt + 1,
                )
                validation = await self._validator.validate(
                    activity,
                    context,
                    response,
                    attempt=attempt + 1,
                )
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                self._trace_logger.warning(
                    "character_response_pipeline:generation_failed",
                    error_type=type(error).__name__,
                    attempt=attempt,
                )
                break
            if validation.accepted:
                self._trace_logger.info(
                    "character_response_pipeline:response_adopted",
                    source_activity_id=activity.activity_id,
                    regenerated=attempt > 0,
                )
                return response, CharacterGenerationResult(
                    status=CharacterGenerationStatus.VALIDATED,
                    activity_turn_id=activity_turn_id,
                    ongoing_activity_id=ongoing_activity_id,
                    source_event_id=activity.source_event_id,
                    adopted_text=response.speech,
                    validation_reason=validation.reason,
                    attempts=attempt + 1,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    trace_id=trace.trace_id,
                    parent_trace_id=trace.parent_trace_id,
                    behavior_plan_id=trace.behavior_plan_id,
                )
            self._trace_logger.warning(
                "character_response_pipeline:response_rejected",
                reason=validation.reason,
                attempt=attempt,
                extracted_claims=[
                    asdict(claim) for claim in validation.extracted_claims
                ],
                claim_differences=list(validation.claim_differences),
            )
            if attempt == 0:
                self._trace_logger.info(
                    "character_response_pipeline:regeneration_requested",
                    source_activity_id=activity.activity_id,
                    reason=validation.reason,
                    invalid_claims=[claim.value for claim in validation.invalid_claims],
                    extracted_claims=[
                        asdict(claim) for claim in validation.extracted_claims
                    ],
                )
        fallback = self._safe_fallback(context)
        self._trace_logger.warning(
            "character_response_pipeline:safe_fallback_used",
            source_activity_id=activity.activity_id,
            execution_status=context.status.value,
            last_validation_reason=(
                validation.reason if validation is not None else None
            ),
        )
        return fallback, CharacterGenerationResult(
            status=CharacterGenerationStatus.FALLBACK_USED,
            activity_turn_id=activity_turn_id,
            ongoing_activity_id=ongoing_activity_id,
            source_event_id=activity.source_event_id,
            adopted_text=fallback.speech,
            validation_reason=validation.reason if validation is not None else None,
            error=last_error,
            attempts=2 if validation is not None else 1,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            trace_id=trace.trace_id,
            parent_trace_id=trace.parent_trace_id,
            behavior_plan_id=trace.behavior_plan_id,
        )

    @staticmethod
    def _correlation_ids(activity: Activity) -> tuple[str, str | None]:
        turn = activity.context.get("activity_turn")
        turn_id = getattr(turn, "turn_id", None)
        ongoing = activity.context.get("ongoing_activity")
        ongoing_id = getattr(ongoing, "ongoing_activity_id", None)
        context_turn_id = activity.context.get("activity_turn_id")
        trace = trace_context_from(activity.context)
        return (
            str(
                turn_id
                or context_turn_id
                or (trace.activity_turn_id if trace is not None else None)
                or activity.activity_id
            ),
            (
                str(
                    ongoing_id
                    or (trace.ongoing_activity_id if trace is not None else None)
                )
                if ongoing_id is not None
                or (trace is not None and trace.ongoing_activity_id)
                else None
            ),
        )

    @staticmethod
    def _correction(
        validation: ResponseValidationResult,
        context: ResponseContext,
    ) -> str:
        return json.dumps(
            {
                "reason": validation.reason,
                "invalid_self_reported_claims": [
                    claim.value for claim in validation.invalid_claims
                ],
                "invalid_speech_claims": [
                    asdict(claim) for claim in validation.extracted_claims
                ],
                "claim_differences": list(validation.claim_differences),
                "execution_status": context.status.value,
                "activity_type": context.activity_type,
                "operation": context.operation,
                "allowed_claims": [claim.value for claim in context.allowed_claims],
                "forbidden_claims": [claim.value for claim in context.forbidden_claims],
                "instruction": "未実行処理を実行済みと表現しない",
            },
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _safe_fallback(context: ResponseContext) -> CharacterResponse:
        if context.status in {
            ActivityExecutionStatus.REJECTED,
            ActivityExecutionStatus.FAILED,
            ActivityExecutionStatus.CANCELED,
        }:
            return CharacterResponse(
                speech="今はそれを一緒にできないんだ。別のお話をしよう。",
                expression="soft_smile",
                claims=(ResponseClaim.EXECUTION_UNAVAILABLE,),
            )
        return CharacterResponse(
            speech="うまく言葉にできなかったみたい。もう一度話しかけてね。",
            expression="soft_smile",
            claims=(ResponseClaim.CONVERSATION_ONLY,),
        )
