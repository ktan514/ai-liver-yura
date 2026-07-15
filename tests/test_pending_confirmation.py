from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.domain.behavior import ActivityOperation, ActivityPlan, BehaviorDecision
from app.domain.pending_confirmation import (
    ConfirmationResolution,
    ConfirmationResolutionKind,
    ConfirmationStatus,
    ConfirmationType,
    PendingConfirmation,
)
from app.runtime import ActivityManager, AgentLifeService
from app.runtime.pending_confirmation import ConfirmationResolver, PendingConfirmationManager


def _plan() -> ActivityPlan:
    return ActivityPlan(
        decision=BehaviorDecision.ASK_CONFIRMATION,
        activity_type="shiritori",
        goal="深海魚縛りのしりとりを開始する",
        required_capability="games.shiritori",
        provider_plugin_id="games",
        operation=ActivityOperation.START,
        constraints={"theme": "深海魚"},
        confidence=0.6,
        reason="semantic_confidence_below_threshold",
    )


def _pending(
    manager: PendingConfirmationManager,
    *,
    now: datetime | None = None,
) -> PendingConfirmation:
    return manager.create(
        _plan(),
        source_event_id="event-1",
        current_ongoing_activity_id="ongoing-1",
        context_snapshot={"situation_analysis": {"confidence": 0.6}},
        now=now,
    )


def test_manager_keeps_candidate_and_supersedes_previous_confirmation() -> None:
    manager = PendingConfirmationManager(timeout_seconds=30, max_attempts=2)
    first = _pending(manager)

    second = manager.create(
        replace(_plan(), goal="別の候補"),
        source_event_id="event-2",
        current_ongoing_activity_id=None,
        context_snapshot={},
    )

    assert first.confirmation_id != second.confirmation_id
    assert second.candidate_constraints == {"theme": "深海魚"}
    assert second.confirmation_type == ConfirmationType.CONFIRM_START_ACTIVITY
    assert manager.history[-1].status == ConfirmationStatus.SUPERSEDED


def test_manager_expires_and_releases_autonomous_suppression() -> None:
    now = datetime.now(timezone.utc)
    manager = PendingConfirmationManager(timeout_seconds=10, max_attempts=2)
    pending = _pending(manager, now=now)
    service = AgentLifeService(
        ActivityManager(),
        now=now,
        pending_confirmation_provider=manager.has_pending,
    )

    assert service.plan_next_event(now=now + timedelta(seconds=1)) is None
    assert manager.current(now=now + timedelta(seconds=11)) is None
    assert manager.history[-1].confirmation_id == pending.confirmation_id
    assert manager.history[-1].status == ConfirmationStatus.EXPIRED


def test_resolver_distinguishes_answers_from_quote_past_negation_and_correction() -> None:
    manager = PendingConfirmationManager()
    pending = _pending(manager)
    resolver = ConfirmationResolver()

    assert resolver.resolve("はい", pending).kind == ConfirmationResolutionKind.AFFIRMATIVE
    assert resolver.resolve("いいえ", pending).kind == ConfirmationResolutionKind.NEGATIVE
    assert resolver.resolve("確認はいい", pending).kind == ConfirmationResolutionKind.CANCEL
    assert (
        resolver.resolve("それより検索して", pending).kind == ConfirmationResolutionKind.NEW_REQUEST
    )
    for text in ("「はい」と言ったらどうなる？", "さっきは「うん」って言ったよ", "はいじゃない"):
        assert resolver.resolve(text, pending).kind == ConfirmationResolutionKind.AMBIGUOUS
    clarification = resolver.resolve("うん、でも停止じゃなくて一時停止", pending)
    assert clarification.kind == ConfirmationResolutionKind.CLARIFICATION
    assert clarification.constraint_updates == {"requested_transition": "pause"}


def test_clarification_updates_candidate_and_attempt_limit_is_finite() -> None:
    manager = PendingConfirmationManager(max_attempts=2)
    pending = _pending(manager)
    clarification = ConfirmationResolution(
        kind=ConfirmationResolutionKind.CLARIFICATION,
        confidence=0.95,
        reason="explicit_correction",
        constraint_updates={"theme": "深海生物"},
    )

    revised = manager.revise(pending, clarification, source_event_id="event-2")

    assert revised is not None
    assert revised.attempt_count == 1
    assert revised.candidate_constraints == {"theme": "深海生物"}
    assert manager.revise(revised, clarification, source_event_id="event-3") is None
    assert manager.history[-1].status == ConfirmationStatus.FAILED


def test_positive_and_negative_resolution_are_terminal() -> None:
    for kind, expected in (
        (ConfirmationResolutionKind.AFFIRMATIVE, ConfirmationStatus.RESOLVED_POSITIVE),
        (ConfirmationResolutionKind.NEGATIVE, ConfirmationStatus.RESOLVED_NEGATIVE),
    ):
        manager = PendingConfirmationManager()
        pending = _pending(manager)
        resolved = manager.resolve(
            pending,
            ConfirmationResolution(kind=kind, confidence=1.0, reason="test"),
            resolution_event_id="event-2",
        )

        assert resolved.status == expected
        assert manager.current() is None
        assert manager.history[-1].resolution_event_id == "event-2"
