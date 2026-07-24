from __future__ import annotations

import re
from dataclasses import asdict

from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    Claim,
    ClaimType,
    ResponseClaim,
    ResponseContext,
    ResponseValidationResult,
)
from app.utils.trace import TraceLogger

_POSITIVE_EXECUTION_CLAIMS = frozenset(
    {
        ClaimType.ACTIVITY_STARTED,
        ClaimType.ACTIVITY_RUNNING,
        ClaimType.ACTIVITY_CONTINUED,
        ClaimType.ACTIVITY_COMPLETED,
        ClaimType.ACTIVITY_SUCCEEDED,
        ClaimType.EXTERNAL_RESULT_OBTAINED,
    }
)
_COMPLETION_CLAIMS = frozenset(
    {
        ClaimType.ACTIVITY_COMPLETED,
        ClaimType.ACTIVITY_SUCCEEDED,
        ClaimType.EXTERNAL_RESULT_OBTAINED,
    }
)
_NEGATIVE_EXECUTION_CLAIMS = frozenset(
    {
        ClaimType.ACTIVITY_FAILED,
        ClaimType.ACTIVITY_REJECTED,
        ClaimType.ACTIVITY_CANCELED,
        ClaimType.CAPABILITY_UNAVAILABLE,
    }
)


class IndependentClaimExtractor:
    """Activity名ではなく実行状態を表す述語から発話の事実主張を抽出する。"""

    _non_assertive_markers = (
        "もし",
        "仮に",
        "としたら",
        "とすれば",
        "場合は",
        "かもしれない",
        "できたら",
        "でしょうか",
        "ですか",
        "ますか",
        "？",
        "?",
    )
    _rules = (
        (
            ClaimType.EXTERNAL_RESULT_OBTAINED,
            re.compile(
                r"(?:結果|データ|情報)(?:を|が)?(?:取得|受信|入手|獲得)(?:した|しました|できた)"
                r"|検索結果(?:を|が)?(?:得られた|見つかった|取得した)"
            ),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_FAILED,
            re.compile(r"(?:失敗した|失敗しました|実行できなかった|処理できなかった)"),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_REJECTED,
            re.compile(r"(?:拒否された|拒否しました|受け付けられなかった)"),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_CANCELED,
            re.compile(r"(?:キャンセル|中止|取り消し)(?:した|しました|された)"),
            0.99,
        ),
        (
            ClaimType.CAPABILITY_UNAVAILABLE,
            re.compile(
                r"(?:今は|現在は)?(?:利用|実行|対応)?できない|利用できません|対応していない"
            ),
            0.96,
        ),
        (
            ClaimType.ACTIVITY_CONTINUED,
            re.compile(
                r"(?:継続|再開)(?:した|しました)|(?:まだ|引き続き).{0,20}続けている"
            ),
            0.98,
        ),
        (
            ClaimType.ACTIVITY_RUNNING,
            re.compile(
                r"(?:実行|処理|進行|稼働)(?:中|している)|(?:ゲーム|活動).{0,12}続けている"
            ),
            0.98,
        ),
        (
            ClaimType.ACTIVITY_COMPLETED,
            re.compile(r"(?:完了|終了)(?:した|しました|したよ)|終えた|済ませた"),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_STARTED,
            re.compile(r"(?:開始|起動|始動|スタート)(?:した|しました|したよ)|始めた"),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_SUCCEEDED,
            re.compile(
                r"(?:成功した|成功しました|うまくいった)"
                r"|(?:を|が)(?:変更|更新|保存|削除|作成|送信|投稿|再生|停止)(?:した|しました|したよ)"
            ),
            0.97,
        ),
        (
            ClaimType.CAPABILITY_AVAILABLE,
            re.compile(r"(?:利用|実行|対応)(?:できる|可能です)|対応している"),
            0.94,
        ),
    )

    def __init__(self) -> None:
        self._trace_logger = TraceLogger()

    def extract(self, context: ResponseContext, speech: str) -> tuple[Claim, ...]:
        normalized = speech.strip()
        if not normalized or self._is_non_assertive(normalized):
            claims: tuple[Claim, ...] = ()
        else:
            extracted: list[Claim] = []
            seen: set[ClaimType] = set()
            for claim_type, pattern, confidence in self._rules:
                match = pattern.search(normalized)
                if match is None or claim_type in seen:
                    continue
                seen.add(claim_type)
                extracted.append(
                    Claim(
                        claim_type=claim_type,
                        activity_type=(
                            context.activity_type
                            if context.activity_type != "conversation"
                            else None
                        ),
                        operation=context.operation,
                        status=self._claimed_status(claim_type),
                        target=self._target(normalized, match.start()),
                        confidence=confidence,
                        evidence=match.group(0),
                    )
                )
            claims = tuple(extracted)
        self._trace_logger.debug(
            "response_claim_extractor:extracted",
            activity_type=context.activity_type,
            operation=context.operation,
            execution_status=context.status.value,
            extracted_claims=[asdict(claim) for claim in claims],
        )
        return claims

    @classmethod
    def _is_non_assertive(cls, speech: str) -> bool:
        return any(marker in speech for marker in cls._non_assertive_markers)

    @staticmethod
    def _claimed_status(claim_type: ClaimType) -> ActivityExecutionStatus | None:
        if claim_type in _COMPLETION_CLAIMS:
            return ActivityExecutionStatus.SUCCEEDED
        if claim_type == ClaimType.ACTIVITY_FAILED:
            return ActivityExecutionStatus.FAILED
        if claim_type == ClaimType.ACTIVITY_REJECTED:
            return ActivityExecutionStatus.REJECTED
        if claim_type == ClaimType.ACTIVITY_CANCELED:
            return ActivityExecutionStatus.CANCELED
        if claim_type in {
            ClaimType.ACTIVITY_RUNNING,
            ClaimType.ACTIVITY_CONTINUED,
            ClaimType.ACTIVITY_STARTED,
        }:
            return ActivityExecutionStatus.WAITING_INPUT
        return None

    @staticmethod
    def _target(speech: str, evidence_start: int) -> str | None:
        prefix = speech[max(0, evidence_start - 24) : evidence_start]
        match = re.search(r"([^、。！？!?]{1,20})(?:を|が|は)$", prefix)
        return match.group(1).strip() if match is not None else None


class DeterministicFactValidator:
    """抽出Claimと確定済みResponseContextをLLMより先に照合する。"""

    _self_reported_map = {
        ResponseClaim.ACTIVITY_REQUESTED: ClaimType.ACTIVITY_REQUESTED,
        ResponseClaim.ACTIVITY_STARTED: ClaimType.ACTIVITY_STARTED,
        ResponseClaim.ACTIVITY_RUNNING: ClaimType.ACTIVITY_RUNNING,
        ResponseClaim.ACTIVITY_CONTINUED: ClaimType.ACTIVITY_CONTINUED,
        ResponseClaim.ACTIVITY_COMPLETED: ClaimType.ACTIVITY_COMPLETED,
        ResponseClaim.ACTIVITY_SUCCEEDED: ClaimType.ACTIVITY_SUCCEEDED,
        ResponseClaim.ACTIVITY_FAILED: ClaimType.ACTIVITY_FAILED,
        ResponseClaim.ACTIVITY_REJECTED: ClaimType.ACTIVITY_REJECTED,
        ResponseClaim.ACTIVITY_CANCELED: ClaimType.ACTIVITY_CANCELED,
        ResponseClaim.EXTERNAL_RESULT_OBTAINED: ClaimType.EXTERNAL_RESULT_OBTAINED,
        ResponseClaim.CAPABILITY_AVAILABLE: ClaimType.CAPABILITY_AVAILABLE,
        ResponseClaim.CAPABILITY_UNAVAILABLE: ClaimType.CAPABILITY_UNAVAILABLE,
        ResponseClaim.ACTIVITY_CONTINUES: ClaimType.ACTIVITY_CONTINUED,
        ResponseClaim.EXECUTION_UNAVAILABLE: ClaimType.CAPABILITY_UNAVAILABLE,
        ResponseClaim.CONVERSATION_ONLY: ClaimType.CONVERSATION_ONLY,
    }

    def __init__(self) -> None:
        self._trace_logger = TraceLogger()

    def validate(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        extracted_claims: tuple[Claim, ...],
    ) -> ResponseValidationResult:
        invalid_self_reported = self._invalid_self_reported(context, response)
        extracted_types = {claim.claim_type for claim in extracted_claims}
        self_reported_types = {
            self._self_reported_map[claim]
            for claim in response.claims
            if claim in self._self_reported_map
        }
        self_reported_types.update(claim.claim_type for claim in response.claim_details)
        differences = (
            *self._claim_differences(extracted_types, self_reported_types),
            *self._structured_claim_differences(context, response.claim_details),
        )
        fact_reasons = self._fact_conflicts(
            context.status,
            extracted_types,
            ongoing_status=(
                context.ongoing_activity.ongoing_status
                if context.ongoing_activity is not None
                else None
            ),
        )
        transition_reasons = self._transition_conflicts(context, extracted_types)
        topic_reasons = self._autonomous_topic_conflicts(context, response.speech)
        reasons = tuple(dict.fromkeys((*fact_reasons, *differences, *topic_reasons)))
        reasons = tuple(dict.fromkeys((*reasons, *transition_reasons)))
        accepted = not invalid_self_reported and not reasons
        reason = (
            "deterministic_facts_valid"
            if accepted
            else reasons[0] if reasons else "claims_conflict_with_result"
        )
        result = ResponseValidationResult(
            accepted=accepted,
            reason=reason,
            invalid_claims=invalid_self_reported,
            extracted_claims=extracted_claims,
            claim_differences=reasons,
        )
        fields = {
            "activity_type": context.activity_type,
            "operation": context.operation,
            "execution_status": context.status.value,
            "self_reported_claims": [claim.value for claim in response.claims],
            "self_reported_claim_details": [
                asdict(claim) for claim in response.claim_details
            ],
            "extracted_claims": [asdict(claim) for claim in extracted_claims],
            "claim_differences": list(reasons),
            "accepted": accepted,
        }
        if accepted:
            self._trace_logger.debug("response_fact_validator:accepted", **fields)
        else:
            self._trace_logger.info("response_fact_validator:rejected", **fields)
        return result

    @staticmethod
    def _invalid_self_reported(
        context: ResponseContext, response: CharacterResponse
    ) -> tuple[ResponseClaim, ...]:
        forbidden = tuple(
            claim for claim in response.claims if claim in context.forbidden_claims
        )
        unknown = tuple(
            claim for claim in response.claims if claim not in context.allowed_claims
        )
        return tuple(dict.fromkeys((*forbidden, *unknown)))

    @staticmethod
    def _fact_conflicts(
        status: ActivityExecutionStatus,
        extracted: set[ClaimType],
        *,
        ongoing_status: str | None,
    ) -> tuple[str, ...]:
        invalid: set[ClaimType]
        if status in {ActivityExecutionStatus.REJECTED, ActivityExecutionStatus.FAILED}:
            invalid = set(_POSITIVE_EXECUTION_CLAIMS)
        elif status == ActivityExecutionStatus.CANCELED:
            invalid = {
                ClaimType.ACTIVITY_RUNNING,
                ClaimType.ACTIVITY_CONTINUED,
                ClaimType.ACTIVITY_COMPLETED,
                ClaimType.ACTIVITY_SUCCEEDED,
                ClaimType.EXTERNAL_RESULT_OBTAINED,
            }
        elif status == ActivityExecutionStatus.WAITING_INPUT:
            invalid = set(_COMPLETION_CLAIMS)
        else:
            invalid = set()
        if ongoing_status == "waiting":
            invalid.update(_COMPLETION_CLAIMS)
        elif ongoing_status in {"completed", "canceled"}:
            invalid.update(
                {
                    ClaimType.ACTIVITY_RUNNING,
                    ClaimType.ACTIVITY_CONTINUED,
                }
            )
        conflicts = extracted & invalid
        ordered = sorted(conflicts, key=lambda item: item.value)
        return tuple(
            f"claim_not_supported_by_{status.value}:{claim.value}" for claim in ordered
        )

    @staticmethod
    def _claim_differences(
        extracted: set[ClaimType], self_reported: set[ClaimType]
    ) -> tuple[str, ...]:
        differences: list[str] = []
        extracted_positive = extracted & _POSITIVE_EXECUTION_CLAIMS
        reported_positive = self_reported & _POSITIVE_EXECUTION_CLAIMS
        extracted_negative = extracted & _NEGATIVE_EXECUTION_CLAIMS
        reported_negative = self_reported & _NEGATIVE_EXECUTION_CLAIMS
        if extracted_positive and not reported_positive:
            differences.append("speech_execution_claim_missing_from_self_report")
        if reported_positive and not extracted_positive:
            differences.append("self_reported_execution_claim_missing_from_speech")
        if extracted_positive and (
            ClaimType.CONVERSATION_ONLY in self_reported or reported_negative
        ):
            differences.append("speech_positive_self_report_negative")
        if extracted_negative and reported_positive:
            differences.append("speech_negative_self_report_positive")
        if (
            ClaimType.ACTIVITY_RUNNING in extracted
            and self_reported & _COMPLETION_CLAIMS
        ):
            differences.append("speech_running_self_report_completed")
        if (
            extracted & _COMPLETION_CLAIMS
            and ClaimType.ACTIVITY_CONTINUED in self_reported
        ):
            differences.append("speech_completed_self_report_continued")
        return tuple(differences)

    @staticmethod
    def _transition_conflicts(
        context: ResponseContext,
        extracted: set[ClaimType],
    ) -> tuple[str, ...]:
        conflicts: list[str] = []
        if context.current_activity_preserved and extracted & {
            ClaimType.ACTIVITY_COMPLETED,
            ClaimType.ACTIVITY_CANCELED,
        }:
            conflicts.append("preserved_activity_claimed_stopped")
        if (
            context.ongoing_input_decision
            in {"conversation_about_current", "conversation_unrelated"}
            and extracted & _POSITIVE_EXECUTION_CLAIMS
        ):
            conflicts.append("conversation_claimed_plugin_execution")
        if (
            context.requested_new_activity is not None
            and context.transition_result != "succeeded"
            and ClaimType.ACTIVITY_STARTED in extracted
        ):
            conflicts.append("failed_switch_claimed_new_activity_started")
        if (
            context.ongoing_input_decision == "stop_current"
            and not context.current_activity_stopped
            and ClaimType.ACTIVITY_COMPLETED in extracted
        ):
            conflicts.append("failed_stop_claimed_activity_completed")
        return tuple(conflicts)

    @staticmethod
    def _structured_claim_differences(
        context: ResponseContext,
        claims: tuple[Claim, ...],
    ) -> tuple[str, ...]:
        differences: list[str] = []
        for claim in claims:
            if (
                claim.activity_type is not None
                and claim.activity_type != context.activity_type
            ):
                differences.append("self_reported_activity_type_mismatch")
            if claim.operation is not None and claim.operation != context.operation:
                differences.append("self_reported_operation_mismatch")
            if claim.status is not None and claim.status != context.status:
                differences.append("self_reported_status_mismatch")
        return tuple(dict.fromkeys(differences))

    @staticmethod
    def _autonomous_topic_conflicts(
        context: ResponseContext,
        speech: str,
    ) -> tuple[str, ...]:
        topic = (context.topic or "").strip()
        if (
            context.activity_type != "autonomous_talk"
            or len(topic) < 4
            or len(speech) < 8
        ):
            return ()
        if topic in {
            "いま気になっていること",
            "この配信でこれから話したいこと",
            "気分転換に考えてみたいこと",
            "いまの気分",
        }:
            return ()
        normalized_topic = re.sub(r"[\s、。！？!?・]", "", topic)
        normalized_speech = re.sub(r"[\s、。！？!?・]", "", speech)
        if len(normalized_topic) < 3:
            return ()
        topic_bigrams = {
            normalized_topic[index : index + 2]
            for index in range(len(normalized_topic) - 1)
        }
        if any(token in normalized_speech for token in topic_bigrams):
            return ()
        return ("autonomous_topic_drift",)
