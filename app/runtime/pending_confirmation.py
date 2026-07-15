from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from app.domain.activity_constraints import ConstraintValidationResult
from app.domain.behavior import ActivityOperation, ActivityPlan, BehaviorDecision
from app.domain.pending_confirmation import (
    ConfirmationResolution,
    ConfirmationResolutionKind,
    ConfirmationStatus,
    ConfirmationType,
    PendingConfirmation,
)
from app.utils.trace import TraceLogger


class PendingConfirmationManager:
    """Runtimeで同時に一件だけ存在する確認待ち状態を管理する。"""

    def __init__(self, *, timeout_seconds: float = 30.0, max_attempts: int = 2) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_secondsは0より大きくしてください。")
        if max_attempts <= 0:
            raise ValueError("max_attemptsは1以上にしてください。")
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._current: PendingConfirmation | None = None
        self._history: list[PendingConfirmation] = []
        self._lock = RLock()
        self._trace_logger = TraceLogger()

    @property
    def history(self) -> tuple[PendingConfirmation, ...]:
        with self._lock:
            return tuple(self._history)

    def current(self, *, now: datetime | None = None) -> PendingConfirmation | None:
        current_time = now or datetime.now(timezone.utc)
        with self._lock:
            pending = self._current
            if pending is not None and pending.is_pending and current_time >= pending.expires_at:
                self._finish(pending, ConfirmationStatus.EXPIRED)
                self._trace_logger.info(
                    "pending_confirmation:expired",
                    confirmation_id=pending.confirmation_id,
                )
                return None
            return self._current if self._current and self._current.is_pending else None

    def has_pending(self) -> bool:
        return self.current() is not None

    def create(
        self,
        plan: ActivityPlan,
        *,
        source_event_id: str,
        current_ongoing_activity_id: str | None,
        context_snapshot: dict[str, object],
        now: datetime | None = None,
    ) -> PendingConfirmation:
        created_at = now or datetime.now(timezone.utc)
        with self._lock:
            if self._current is not None and self._current.is_pending:
                previous = self._current
                self._finish(previous, ConfirmationStatus.SUPERSEDED)
                self._trace_logger.info(
                    "pending_confirmation:superseded",
                    confirmation_id=previous.confirmation_id,
                )
            confirmation_type = self._type_for(plan, current_ongoing_activity_id)
            pending = PendingConfirmation(
                confirmation_id=str(uuid4()),
                source_event_id=source_event_id,
                created_at=created_at,
                expires_at=created_at + timedelta(seconds=self._timeout_seconds),
                status=ConfirmationStatus.PENDING,
                confirmation_type=confirmation_type,
                candidate_activity_type=plan.activity_type,
                candidate_operation=plan.operation.value if plan.operation else None,
                candidate_goal=plan.goal,
                candidate_constraints=dict(plan.constraints),
                candidate_confidence=plan.confidence,
                candidate_constraints_schema_version=plan.constraints_schema_version,
                current_ongoing_activity_id=current_ongoing_activity_id,
                question=self._question_for(plan, confirmation_type),
                positive_resolution="候補Activity Planを再検証して実行する",
                negative_resolution="候補を破棄し、現在状態を維持する",
                attempt_count=0,
                max_attempts=self._max_attempts,
                context_snapshot=dict(context_snapshot),
                candidate_plan=plan,
            )
            self._current = pending
            self._trace_logger.info(
                "pending_confirmation:created",
                confirmation_id=pending.confirmation_id,
                confirmation_type=pending.confirmation_type.value,
                candidate_activity_type=pending.candidate_activity_type,
                candidate_operation=pending.candidate_operation,
                ongoing_activity_id=pending.current_ongoing_activity_id,
            )
            self._trace_logger.debug(
                "pending_confirmation:candidate",
                confirmation=asdict(pending),
            )
            return pending

    def resolve(
        self,
        pending: PendingConfirmation,
        resolution: ConfirmationResolution,
        *,
        resolution_event_id: str,
    ) -> PendingConfirmation:
        status = {
            ConfirmationResolutionKind.AFFIRMATIVE: ConfirmationStatus.RESOLVED_POSITIVE,
            ConfirmationResolutionKind.NEGATIVE: ConfirmationStatus.RESOLVED_NEGATIVE,
            ConfirmationResolutionKind.CANCEL: ConfirmationStatus.CANCELED,
            ConfirmationResolutionKind.NEW_REQUEST: ConfirmationStatus.SUPERSEDED,
        }.get(resolution.kind)
        if status is None:
            raise ValueError(f"terminalではないresolutionです: {resolution.kind.value}")
        with self._lock:
            finished = replace(
                pending,
                status=status,
                resolution_event_id=resolution_event_id,
                resolution=resolution.kind,
            )
            self._replace_and_clear(finished)
            self._trace_logger.info(
                f"pending_confirmation:{status.value}",
                confirmation_id=finished.confirmation_id,
                resolution_event_id=resolution_event_id,
            )
            return finished

    def revise(
        self,
        pending: PendingConfirmation,
        resolution: ConfirmationResolution,
        *,
        source_event_id: str,
        constraint_validation: (
            Callable[[ActivityPlan, dict[str, object]], ConstraintValidationResult | None] | None
        ) = None,
    ) -> PendingConfirmation | None:
        with self._lock:
            attempts = pending.attempt_count + 1
            if attempts >= pending.max_attempts:
                failed = replace(
                    pending,
                    status=ConfirmationStatus.FAILED,
                    attempt_count=attempts,
                    resolution_event_id=source_event_id,
                    resolution=resolution.kind,
                )
                self._replace_and_clear(failed)
                self._trace_logger.info(
                    "pending_confirmation:max_attempts_reached",
                    confirmation_id=pending.confirmation_id,
                    attempts=attempts,
                )
                return None
            plan = pending.candidate_plan
            if resolution.kind == ConfirmationResolutionKind.CLARIFICATION:
                operation = self._operation(resolution.operation) or plan.operation
                constraints = {**plan.constraints, **resolution.constraint_updates}
                validation = (
                    constraint_validation(plan, constraints)
                    if constraint_validation is not None
                    else None
                )
                if validation is None or validation.valid:
                    plan = replace(
                        plan,
                        operation=operation,
                        constraints=(
                            dict(validation.normalized_constraints)
                            if validation is not None
                            else constraints
                        ),
                        constraint_errors=(),
                        constraints_schema_version=(
                            validation.schema_version
                            if validation is not None
                            else plan.constraints_schema_version
                        ),
                        validated_constraints=(
                            validation.as_validated() if validation is not None else None
                        ),
                    )
                elif validation is not None:
                    plan = replace(plan, constraint_errors=validation.errors)
                    self._trace_logger.info(
                        "activity_constraints:confirmation_still_invalid",
                        confirmation_id=pending.confirmation_id,
                        activity_type=plan.activity_type,
                        source="confirmation",
                        schema_version=validation.schema_version,
                        errors=[error.code for error in validation.errors],
                    )
            revised = replace(
                pending,
                attempt_count=attempts,
                source_event_id=source_event_id,
                candidate_operation=plan.operation.value if plan.operation else None,
                candidate_constraints=dict(plan.constraints),
                candidate_constraints_schema_version=plan.constraints_schema_version,
                candidate_plan=plan,
                question=self._question_for(plan, pending.confirmation_type),
            )
            self._current = revised
            self._trace_logger.debug(
                "pending_confirmation:revised",
                confirmation_id=revised.confirmation_id,
                resolution=resolution.kind.value,
                attempts=attempts,
                candidate_plan=plan,
            )
            return revised

    def _finish(self, pending: PendingConfirmation, status: ConfirmationStatus) -> None:
        self._replace_and_clear(replace(pending, status=status))

    def _replace_and_clear(self, finished: PendingConfirmation) -> None:
        self._history.append(finished)
        self._current = None

    @staticmethod
    def _operation(value: str | None) -> ActivityOperation | None:
        try:
            return ActivityOperation(value) if value is not None else None
        except ValueError:
            return None

    @staticmethod
    def _type_for(plan: ActivityPlan, ongoing_id: str | None) -> ConfirmationType:
        if plan.constraint_errors:
            return ConfirmationType.CONFIRM_CONSTRAINTS
        if plan.decision == BehaviorDecision.SWITCH_ACTIVITY or plan.requested_new_activity:
            return ConfirmationType.CONFIRM_SWITCH_ACTIVITY
        if plan.operation == ActivityOperation.STOP:
            return ConfirmationType.CONFIRM_STOP_ACTIVITY
        if plan.operation == ActivityOperation.START:
            return ConfirmationType.CONFIRM_START_ACTIVITY
        if plan.operation == ActivityOperation.CONTINUE and ongoing_id:
            return ConfirmationType.CONFIRM_CONTINUE_ACTIVITY
        if plan.constraints:
            return ConfirmationType.CONFIRM_CONSTRAINTS
        return ConfirmationType.CONFIRM_INTERPRETATION

    @staticmethod
    def _question_for(plan: ActivityPlan, confirmation_type: ConfirmationType) -> str:
        target = plan.goal.strip() or plan.activity_type
        if confirmation_type == ConfirmationType.CONFIRM_STOP_ACTIVITY:
            return f"「{target}」という意味で、今やっていることを終えてよいか確認する"
        if confirmation_type == ConfirmationType.CONFIRM_SWITCH_ACTIVITY:
            return f"今やっていることから「{target}」へ切り替えてよいか確認する"
        return f"「{target}」という意図で合っているか確認する"


class ConfirmationResolver:
    """確認回答を高精度な意味パターンで安全に分類する。"""

    _quoted_or_non_current = re.compile(
        r"[「『\"].*(はい|うん).*[」』\"]|(?:はい|うん).*(?:と言ったら|って言った|と言った|だった)|"
        r"(?:さっき|昨日|前に).*(?:はい|うん)|(?:はい|うん)じゃない"
    )
    _clarification = re.compile(r"(?:じゃなくて|ではなく|でなく|ただし|でも).+")
    _cancel = re.compile(
        r"^(?:確認は(?:いい|不要)|何もしないで|取り消して|キャンセル)(?:[。！!]*)$"
    )
    _negative = re.compile(
        r"^(?:いいえ|いや|違う|ちがう|やめて|やめよう|そういう意味じゃない|しない)(?:[。！!]*)$"
    )
    _affirmative = re.compile(
        r"^(?:はい|うん|ええ|お願い|それでお願い|そうして|それで合ってる|その通り|OK|ok)(?:[。！!]*)$"
    )
    _new_request = re.compile(r"^(?:それより|代わりに|別の|話は変わるけど|ところで).+")
    _theme = re.compile(r"(?:テーマ|縛り|対象)は?(.+?)(?:にして|でお願い|に変更|$)")

    def __init__(self) -> None:
        self._trace_logger = TraceLogger()

    def resolve(self, text: str, pending: PendingConfirmation) -> ConfirmationResolution:
        normalized = re.sub(r"\s+", "", text.strip())
        if self._quoted_or_non_current.search(normalized):
            result = self._result(
                ConfirmationResolutionKind.AMBIGUOUS, 0.98, "non_current_reference"
            )
        elif self._clarification.search(normalized):
            updates: dict[str, object] = {}
            theme = self._theme.search(normalized)
            if theme:
                updates["theme"] = theme.group(1)
            operation = "continue" if "一時停止" in normalized else None
            if "一時停止" in normalized:
                updates["requested_transition"] = "pause"
            result = self._result(
                ConfirmationResolutionKind.CLARIFICATION,
                0.95,
                "explicit_correction",
                operation=operation,
                constraint_updates=updates,
            )
        elif self._cancel.fullmatch(normalized):
            result = self._result(ConfirmationResolutionKind.CANCEL, 1.0, "explicit_cancel")
        elif self._negative.fullmatch(normalized):
            result = self._result(ConfirmationResolutionKind.NEGATIVE, 1.0, "explicit_negative")
        elif self._affirmative.fullmatch(normalized):
            result = self._result(
                ConfirmationResolutionKind.AFFIRMATIVE, 1.0, "explicit_affirmative"
            )
        elif self._new_request.match(normalized):
            result = self._result(
                ConfirmationResolutionKind.NEW_REQUEST, 0.95, "explicit_topic_change"
            )
        elif len(normalized) >= 8 and any(
            ending in normalized for ending in ("して", "しよう", "教えて", "調べて", "話そう")
        ):
            result = self._result(
                ConfirmationResolutionKind.NEW_REQUEST, 0.8, "independent_request"
            )
        else:
            result = self._result(
                ConfirmationResolutionKind.AMBIGUOUS, 0.5, "no_high_precision_match"
            )
        self._trace_logger.debug(
            "pending_confirmation:input_classified",
            confirmation_id=pending.confirmation_id,
            resolution=result.kind.value,
            confidence=result.confidence,
            reason=result.reason,
        )
        return result

    @staticmethod
    def _result(
        kind: ConfirmationResolutionKind,
        confidence: float,
        reason: str,
        *,
        operation: str | None = None,
        constraint_updates: dict[str, object] | None = None,
    ) -> ConfirmationResolution:
        return ConfirmationResolution(
            kind=kind,
            confidence=confidence,
            reason=reason,
            operation=operation,
            constraint_updates=constraint_updates or {},
        )
