from __future__ import annotations

import threading

from app.domain.activities import (
    Activity,
    ActivityResult,
    ActivityStatus,
    ActivityType,
    OngoingActivity,
)
from app.domain.activity_turn_result import ActivityOutputResult, ActivityTurnResult
from app.domain.character_response import ActivityExecutionResult
from app.domain.events import AgentEvent, AgentEventType
from app.domain.games import GameSession
from app.runtime.game_engine import GameEngine
from app.utils.trace import TraceLogger


class ActivityManager:
    """Activity の生成・前面化・保留・一時停止を管理する。"""

    def __init__(self, game_engine: GameEngine | None = None) -> None:
        self._activities: dict[str, Activity] = {}
        self._foreground_activity_id: str | None = None
        self._ongoing_activity: OngoingActivity | None = None
        self._ongoing_activity_history: list[OngoingActivity] = []
        self._last_activity_result: ActivityResult | None = None
        self._turn_results: dict[str, ActivityTurnResult] = {}
        self._game_engine = game_engine
        self._lock = threading.RLock()
        self._trace_logger = TraceLogger()

    @property
    def foreground_activity(self) -> Activity | None:
        with self._lock:
            if self._foreground_activity_id is None:
                return None
            return self._activities.get(self._foreground_activity_id)

    def get_activity(self, activity_id: str) -> Activity | None:
        with self._lock:
            return self._activities.get(activity_id)

    @property
    def game_engine(self) -> GameEngine:
        if self._game_engine is None:
            self._game_engine = GameEngine()
        return self._game_engine

    def register_plugin_activity(self, activity: Activity) -> Activity:
        """Pluginが要求した汎用ActivityをCoreのライフサイクルへ登録する。"""

        with self._lock:
            return self._resolve_activity(activity)

    def start_game_activity(
        self,
        game_type: str,
        *,
        goal: str,
        priority: int = 100,
        metadata: dict[str, object] | None = None,
    ) -> tuple[GameSession, Activity]:
        """明示的な呼び出しでSessionを開始し、既存Runtime用Activityへ接続する。"""

        with self._lock:
            session = self.game_engine.start_game(game_type, metadata=metadata)
            return session, self.create_game_activity(
                session,
                goal=goal,
                priority=priority,
            )

    def create_game_activity(
        self,
        session: GameSession,
        *,
        goal: str,
        priority: int = 100,
        context_updates: dict[str, object] | None = None,
    ) -> Activity:
        """GameSessionを参照するActivityを通常のActivity管理へ登録する。"""

        with self._lock:
            current_session = self.game_engine.get_current_session()
            if current_session is None or current_session.session_id != session.session_id:
                raise ValueError("GameEngineが管理していないSessionのActivityは作成できません。")
            activity = Activity(
                activity_type=ActivityType.GAME_WITH_USER,
                goal=goal,
                priority=priority,
                context={
                    "game_session_id": session.session_id,
                    "game_type": session.game_type,
                    "game_status": session.status.value,
                    "game_metadata": dict(session.metadata),
                    "game_current_turn": session.current_turn,
                    **(context_updates or {}),
                },
                interruptible=False,
            )
            resolved = self._resolve_activity(activity)
            self._trace_logger.info(
                "activity_manager:game_activity:created",
                activity_id=resolved.activity_id,
                activity_status=resolved.status.value,
                session_id=session.session_id,
                game_type=session.game_type,
            )
            return resolved

    @property
    def ongoing_activity(self) -> OngoingActivity | None:
        with self._lock:
            return self._ongoing_activity

    @property
    def last_activity_result(self) -> ActivityResult | None:
        with self._lock:
            return self._last_activity_result

    def start_ongoing_activity(
        self,
        *,
        activity_type: str,
        goal: str,
        expected_input: str,
        end_condition: str,
        context: dict[str, object] | None = None,
    ) -> OngoingActivity:
        """複数ターン活動を開始し、次のUSER_TEXTまで保持する。"""

        with self._lock:
            if self._ongoing_activity is not None:
                self._end_ongoing_activity_locked(reason="replaced_by_new_activity")
            ongoing = OngoingActivity(
                activity_type=activity_type,
                goal=goal,
                expected_input=expected_input,
                end_condition=end_condition,
                context=dict(context or {}),
            )
            self._ongoing_activity = ongoing
            self._trace_logger.info(
                "activity_manager:ongoing_activity:started",
                ongoing_activity_id=ongoing.ongoing_activity_id,
                ongoing_activity_type=ongoing.activity_type,
                goal=ongoing.goal,
                expected_input=ongoing.expected_input,
                end_condition=ongoing.end_condition,
            )
            return ongoing

    def update_ongoing_activity(
        self,
        *,
        result: ActivityResult | None = None,
        expected_input: str | None = None,
        context_updates: dict[str, object] | None = None,
    ) -> OngoingActivity | None:
        with self._lock:
            current = self._ongoing_activity
            if current is None:
                return None
            updated = current.updated(
                result=result,
                expected_input=expected_input,
                context_updates=context_updates,
            )
            self._ongoing_activity = updated
            self._trace_logger.info(
                "activity_manager:ongoing_activity:updated",
                ongoing_activity_id=updated.ongoing_activity_id,
                ongoing_activity_type=updated.activity_type,
                result_type=updated.last_result.result_type if updated.last_result else None,
                result_succeeded=updated.last_result.succeeded if updated.last_result else None,
                expected_input=updated.expected_input,
                updated_context_keys=sorted((context_updates or {}).keys()),
            )
            return updated

    def begin_ongoing_turn(
        self,
        *,
        input_text: str,
        source_event_id: str | None,
        operation: str | None,
        constraints_snapshot: dict[str, object] | None = None,
    ) -> OngoingActivity | None:
        with self._lock:
            current = self._ongoing_activity
            if current is None:
                return None
            updated = current.begin_turn(
                input_text,
                source_event_id,
                operation=operation,
                constraints_snapshot=constraints_snapshot,
            )
            self._ongoing_activity = updated
            turn = updated.turns[-1]
            self._trace_logger.info(
                "activity_manager:ongoing_activity:turn_started",
                ongoing_activity_id=updated.ongoing_activity_id,
                activity_turn_id=turn.turn_id,
                source_event_id=source_event_id,
                operation=operation,
                constraints_snapshot=turn.constraints_snapshot,
            )
            return updated

    def record_ongoing_execution(
        self,
        result: ActivityExecutionResult,
        *,
        expected_input: str | None = None,
        context_updates: dict[str, object] | None = None,
        waiting_input: bool = True,
    ) -> OngoingActivity | None:
        with self._lock:
            current = self._ongoing_activity
            if current is None:
                return None
            updated = current.record_execution(
                result,
                expected_input=expected_input,
                context_updates=context_updates,
                waiting_input=waiting_input,
            )
            self._ongoing_activity = updated
            turn = updated.turns[-1] if updated.turns else None
            self._trace_logger.info(
                "activity_manager:ongoing_activity:execution_recorded",
                ongoing_activity_id=updated.ongoing_activity_id,
                activity_turn_id=turn.turn_id if turn is not None else None,
                execution_status=result.status.value,
                ongoing_status=updated.status.value,
                expected_input=updated.expected_input,
            )
            return updated

    def record_turn_result(self, result: ActivityTurnResult) -> ActivityTurnResult:
        """段階別結果をTurn単位で保存し、該当するOngoing Turnへ反映する。"""

        with self._lock:
            self._turn_results[result.activity_turn_id] = result
            current = self._ongoing_activity
            if (
                current is not None
                and result.ongoing_activity_id == current.ongoing_activity_id
                and current.turns
                and current.turns[-1].turn_id == result.activity_turn_id
            ):
                updated = current
                if result.character_result is not None:
                    updated = updated.record_character(result.character_result)
                if result.output_result is not None:
                    updated = updated.record_output(result.output_result)
                self._ongoing_activity = updated
            self._trace_logger.info(
                "activity_manager:activity_turn:result_recorded",
                activity_turn_id=result.activity_turn_id,
                ongoing_activity_id=result.ongoing_activity_id,
                activity_execution_result_id=result.execution_result.result_id
                if result.execution_result is not None
                else None,
                character_generation_result_id=result.character_result.result_id
                if result.character_result is not None
                else None,
                output_unit_id=result.output_result.output_unit_id
                if result.output_result is not None
                else None,
                activity_result_id=result.output_result.activity_result_id
                if result.output_result is not None
                else None,
                final_status=result.final_status,
                failure_stage=result.failure_stage,
            )
            return result

    def get_turn_result(self, activity_turn_id: str) -> ActivityTurnResult | None:
        with self._lock:
            return self._turn_results.get(activity_turn_id)

    def record_output_result(
        self, base: ActivityTurnResult, output: ActivityOutputResult
    ) -> ActivityTurnResult:
        return self.record_turn_result(base.with_output(output))

    def end_ongoing_activity(self, *, reason: str) -> OngoingActivity | None:
        with self._lock:
            return self._end_ongoing_activity_locked(reason=reason)

    def cancel_ongoing_activity(self, *, reason: str) -> OngoingActivity | None:
        with self._lock:
            current = self._ongoing_activity
            if current is None:
                return None
            canceled = current.canceled()
            self._ongoing_activity_history.append(canceled)
            self._ongoing_activity = None
            self._trace_logger.info(
                "activity_manager:ongoing_activity:canceled",
                ongoing_activity_id=canceled.ongoing_activity_id,
                ongoing_activity_type=canceled.activity_type,
                reason=reason,
            )
            return canceled

    def pause_ongoing_activity(self, *, reason: str) -> OngoingActivity | None:
        with self._lock:
            current = self._ongoing_activity
            if current is None:
                return None
            paused = current.paused()
            self._ongoing_activity = paused
            self._trace_logger.info(
                "activity_manager:ongoing_activity:paused",
                ongoing_activity_id=paused.ongoing_activity_id,
                ongoing_activity_type=paused.activity_type,
                reason=reason,
            )
            return paused

    @property
    def ongoing_activity_history(self) -> tuple[OngoingActivity, ...]:
        with self._lock:
            return tuple(self._ongoing_activity_history)

    def _end_ongoing_activity_locked(self, *, reason: str) -> OngoingActivity | None:
        current = self._ongoing_activity
        if current is None:
            return None
        completed = current.completed()
        self._ongoing_activity_history.append(completed)
        self._ongoing_activity = None
        self._trace_logger.info(
            "activity_manager:ongoing_activity:completed",
            ongoing_activity_id=completed.ongoing_activity_id,
            ongoing_activity_type=completed.activity_type,
            reason=reason,
        )
        return completed

    def prepare_user_input(self, event: AgentEvent) -> Activity | None:
        """USER_TEXT受理時に自律Activityを退避し、会話を予約する。"""

        if event.event_type != AgentEventType.USER_TEXT:
            return None
        with self._lock:
            prepared = self._find_by_source_event(event.event_id)
            if prepared is not None:
                return prepared
            current = self.foreground_activity
            if (
                current is None
                or current.activity_type != ActivityType.AUTONOMOUS_TALK
                or not current.interruptible
            ):
                return None

            suspended = current.with_status(ActivityStatus.SUSPENDED)
            self._activities[current.activity_id] = suspended
            conversation = self._create_activity_from_event(event)
            active_conversation = self._activate(conversation)
            self._trace_logger.info(
                "activity_manager:user_input:autonomous_suspended",
                activity_id=suspended.activity_id,
                activity_type=suspended.activity_type.value,
                source_event_id=event.event_id,
                reason="user_text_received",
            )
            self._trace_logger.info(
                "activity_manager:user_input:conversation_prepared",
                activity_id=active_conversation.activity_id,
                source_event_id=event.event_id,
            )
            return active_conversation

    def handle_event(self, event: AgentEvent) -> Activity:
        """イベントから Activity を生成し、現在の foreground と調停する。

        戻り値は、ActionPlanner が今回のイベントに対して扱う Activity。
        foreground になれない場合は pending Activity を返す。
        """
        with self._lock:
            return self._handle_event_locked(event)

    def _handle_event_locked(self, event: AgentEvent) -> Activity:
        prepared = self._find_by_source_event(event.event_id)
        if prepared is not None:
            self._trace_logger.info(
                "activity_manager:handle_event:prepared_activity_reused",
                activity_id=prepared.activity_id,
                activity_type=prepared.activity_type.value,
                event_id=event.event_id,
            )
            return prepared
        self._trace_logger.write(
            "activity_manager:handle_event:start",
            event_type=event.event_type.value,
            event_id=event.event_id,
            event_priority=event.priority,
            foreground_activity_id=self._foreground_activity_id,
        )
        new_activity = self._create_activity_from_event(event)
        self._trace_logger.write(
            "activity_manager:handle_event:activity_created",
            activity_id=new_activity.activity_id,
            activity_type=new_activity.activity_type.value,
            activity_status=new_activity.status.value,
            activity_priority=new_activity.priority,
            interruptible=new_activity.interruptible,
            source_event_id=new_activity.source_event_id,
        )
        resolved_activity = self._resolve_activity(new_activity)
        self._trace_logger.write(
            "activity_manager:handle_event:resolved",
            activity_id=resolved_activity.activity_id,
            activity_type=resolved_activity.activity_type.value,
            activity_status=resolved_activity.status.value,
            activity_priority=resolved_activity.priority,
            foreground_activity_id=self._foreground_activity_id,
        )
        return resolved_activity

    def _find_by_source_event(self, event_id: str) -> Activity | None:
        return next(
            (
                activity
                for activity in self._activities.values()
                if activity.source_event_id == event_id
            ),
            None,
        )

    def list_activities(self) -> list[Activity]:
        return list(self._activities.values())

    def pending_activities(self) -> list[Activity]:
        return [
            activity
            for activity in self._activities.values()
            if activity.status == ActivityStatus.PENDING
        ]

    def suspended_activities(self) -> list[Activity]:
        return [
            activity
            for activity in self._activities.values()
            if activity.status == ActivityStatus.SUSPENDED
        ]

    def complete_activity(self, activity_id: str) -> Activity | None:
        activity = self._activities.get(activity_id)
        if activity is None:
            return None

        self._trace_logger.write(
            "activity_manager:complete_activity:start",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            activity_status=activity.status.value,
            foreground_activity_id=self._foreground_activity_id,
        )

        completed = activity.with_status(ActivityStatus.COMPLETED)
        self._activities[activity_id] = completed

        if self._foreground_activity_id == activity_id:
            self._foreground_activity_id = None

        self._trace_logger.write(
            "activity_manager:complete_activity:completed",
            activity_id=completed.activity_id,
            activity_type=completed.activity_type.value,
            activity_status=completed.status.value,
            foreground_activity_id=self._foreground_activity_id,
        )
        return completed

    def cancel_activity(self, activity_id: str, *, reason: str) -> Activity | None:
        """未完了Activityをキャンセルし、foregroundなら解除する。"""

        with self._lock:
            activity = self._activities.get(activity_id)
            if activity is None:
                return None
            if activity.status in {ActivityStatus.COMPLETED, ActivityStatus.CANCELED}:
                return activity
            canceled = activity.with_status(ActivityStatus.CANCELED)
            self._activities[activity_id] = canceled
            if self._foreground_activity_id == activity_id:
                self._foreground_activity_id = None
            self._trace_logger.info(
                "activity_manager:activity_canceled",
                activity_id=canceled.activity_id,
                activity_type=canceled.activity_type.value,
                previous_status=activity.status.value,
                activity_source_event_id=canceled.source_event_id,
                reason=reason,
            )
            return canceled

    def discard_deferred_autonomous(self, *, reason: str) -> list[Activity]:
        """会話前に保留・退避された古い自律Activityを再開対象から外す。"""

        with self._lock:
            targets = [
                activity
                for activity in self._activities.values()
                if activity.activity_type == ActivityType.AUTONOMOUS_TALK
                and activity.status in {ActivityStatus.PENDING, ActivityStatus.SUSPENDED}
            ]
            discarded: list[Activity] = []
            for activity in targets:
                canceled = self.cancel_activity(activity.activity_id, reason=reason)
                if canceled is not None:
                    discarded.append(canceled)
            if discarded:
                self._trace_logger.info(
                    "activity_manager:deferred_autonomous:discarded",
                    activity_ids=[activity.activity_id for activity in discarded],
                    reason=reason,
                )
            return discarded

    def complete_foreground_activity(self) -> Activity | None:
        foreground = self.foreground_activity
        if foreground is None:
            self._trace_logger.write("activity_manager:complete_foreground_activity:no_foreground")
            return None

        self._trace_logger.write(
            "activity_manager:complete_foreground_activity:start",
            activity_id=foreground.activity_id,
            activity_type=foreground.activity_type.value,
            activity_status=foreground.status.value,
        )

        if foreground.activity_type == ActivityType.CONVERSATION_WITH_USER:
            self.discard_deferred_autonomous(reason="conversation_response_completed")
        completed = self.complete_activity(foreground.activity_id)
        self.resume_next_pending()
        return completed

    def complete_processed_activity(
        self,
        activity_id: str,
        *,
        result: ActivityResult | None = None,
    ) -> Activity | None:
        """実行対象Activityだけを完了し、foregroundだった場合だけ次を再開する。"""

        with self._lock:
            activity = self._activities.get(activity_id)
            ongoing = self._ongoing_activity
            if (
                result is not None
                and activity is not None
                and ongoing is not None
                and activity.context.get("ongoing_activity_id") == ongoing.ongoing_activity_id
            ):
                self.update_ongoing_activity(result=result)
            if result is not None:
                self._last_activity_result = result
            if (
                activity is not None
                and activity.activity_type == ActivityType.CONVERSATION_WITH_USER
            ):
                self.discard_deferred_autonomous(reason="conversation_response_completed")
            was_foreground = self._foreground_activity_id == activity_id
            completed = self.complete_activity(activity_id)
            if was_foreground:
                self.resume_next_pending()
            return completed

    def resume_next_pending(self) -> Activity | None:
        pending_activities = self.pending_activities()
        if not pending_activities:
            self._trace_logger.write("activity_manager:resume_next_pending:no_pending")
            return None

        next_activity = max(pending_activities, key=lambda activity: activity.priority)
        self._trace_logger.write(
            "activity_manager:resume_next_pending:selected",
            activity_id=next_activity.activity_id,
            activity_type=next_activity.activity_type.value,
            activity_priority=next_activity.priority,
            pending_activity_count=len(pending_activities),
        )
        return self._activate(next_activity)

    def _create_activity_from_event(self, event: AgentEvent) -> Activity:
        if event.event_type in (AgentEventType.USER_TEXT, AgentEventType.YOUTUBE_COMMENT):
            ongoing = self._ongoing_activity
            if ongoing is not None:
                ongoing = ongoing.begin_turn(str(event.payload.get("text") or ""), event.event_id)
                self._ongoing_activity = ongoing
            context: dict[str, object] = {
                "event_payload": event.payload,
                "is_ongoing_activity_input": ongoing is not None,
            }
            goal = "ユーザー入力に応答する"
            if ongoing is not None:
                context["ongoing_activity"] = ongoing
                context["ongoing_activity_id"] = ongoing.ongoing_activity_id
                context["activity_turn"] = ongoing.turns[-1]
                goal = f"複数ターン活動「{ongoing.activity_type}」を継続する"
            context["is_ongoing_activity_input"] = ongoing is not None
            return Activity(
                activity_type=ActivityType.CONVERSATION_WITH_USER,
                goal=goal,
                priority=100 + event.priority,
                context=context,
                interruptible=False,
                source_event_id=event.event_id,
            )

        if event.event_type == AgentEventType.APP_STARTED:
            return Activity(
                activity_type=ActivityType.STARTUP_REACTION,
                goal="起動直後の状況に反応し、配信準備中であることを自然に伝える",
                priority=90 + event.priority,
                context={"event_payload": event.payload},
                interruptible=False,
                source_event_id=event.event_id,
            )

        if event.event_type == AgentEventType.STREAM_STARTED:
            return Activity(
                activity_type=ActivityType.STREAM_OPENING_GREETING,
                goal="配信開始時のあいさつをして、これから話し始める雰囲気を作る",
                priority=95 + event.priority,
                context={"event_payload": event.payload},
                interruptible=False,
                source_event_id=event.event_id,
            )

        if event.event_type == AgentEventType.STREAM_ENDING:
            return Activity(
                activity_type=ActivityType.STREAM_CLOSING_GREETING,
                goal="配信終了前のあいさつをして、視聴者に自然に別れを伝える",
                priority=110 + event.priority,
                context={"event_payload": event.payload},
                interruptible=False,
                source_event_id=event.event_id,
            )

        if event.event_type == AgentEventType.CURIOSITY_PEAK:
            behavior_plan_value = event.payload.get("behavior_plan")
            behavior_plan = behavior_plan_value if isinstance(behavior_plan_value, dict) else {}
            return Activity(
                activity_type=ActivityType.AUTONOMOUS_TALK,
                goal=str(behavior_plan.get("goal") or "内的関心に基づいて自律的に話題を出して話す"),
                priority=55 + event.priority,
                context={
                    "event_payload": event.payload,
                    "behavior_plan": behavior_plan,
                    "autonomous_situation_context": event.payload.get(
                        "autonomous_situation_context"
                    ),
                    "autonomous_situation_analysis": event.payload.get(
                        "autonomous_situation_analysis"
                    ),
                    "emotion": (
                        event.payload.get("autonomous_situation_context", {}).get(
                            "emotion_state", {}
                        )
                        if isinstance(event.payload.get("autonomous_situation_context"), dict)
                        else {}
                    ),
                    "drive": (
                        event.payload.get("autonomous_situation_context", {}).get("drive_state", {})
                        if isinstance(event.payload.get("autonomous_situation_context"), dict)
                        else {}
                    ),
                },
                interruptible=True,
                source_event_id=event.event_id,
            )

        if event.event_type == AgentEventType.SILENCE_TIMEOUT:
            return Activity(
                activity_type=ActivityType.IDLE_OBSERVATION,
                goal="配信中の間を観察する",
                priority=15 + event.priority,
                context={"event_payload": event.payload},
                interruptible=True,
                source_event_id=event.event_id,
            )

        return Activity(
            activity_type=ActivityType.IDLE_OBSERVATION,
            goal="状態を観察する",
            priority=10 + event.priority,
            context={"event_payload": event.payload},
            interruptible=True,
            source_event_id=event.event_id,
        )

    def _resolve_activity(self, new_activity: Activity) -> Activity:
        current = self.foreground_activity
        self._trace_logger.write(
            "activity_manager:resolve_activity:start",
            new_activity_id=new_activity.activity_id,
            new_activity_type=new_activity.activity_type.value,
            new_activity_priority=new_activity.priority,
            current_activity_id=current.activity_id if current is not None else None,
            current_activity_type=current.activity_type.value if current is not None else None,
            current_activity_priority=current.priority if current is not None else None,
            current_interruptible=current.interruptible if current is not None else None,
        )

        if current is None:
            self._trace_logger.write(
                "activity_manager:resolve_activity:activate_without_current",
                activity_id=new_activity.activity_id,
                activity_type=new_activity.activity_type.value,
            )
            return self._activate(new_activity)

        if self._should_activate(current, new_activity):
            self._trace_logger.write(
                "activity_manager:resolve_activity:suspend_current",
                current_activity_id=current.activity_id,
                current_activity_type=current.activity_type.value,
                new_activity_id=new_activity.activity_id,
                new_activity_type=new_activity.activity_type.value,
            )
            self._activities[current.activity_id] = current.with_status(ActivityStatus.SUSPENDED)
            return self._activate(new_activity)

        pending = new_activity.with_status(ActivityStatus.PENDING)
        self._trace_logger.write(
            "activity_manager:resolve_activity:pending",
            activity_id=pending.activity_id,
            activity_type=pending.activity_type.value,
            activity_priority=pending.priority,
            foreground_activity_id=self._foreground_activity_id,
        )
        self._activities[pending.activity_id] = pending
        return pending

    def _should_activate(self, current: Activity, new_activity: Activity) -> bool:
        self._trace_logger.write(
            "activity_manager:should_activate:evaluate",
            current_activity_id=current.activity_id,
            current_activity_type=current.activity_type.value,
            current_priority=current.priority,
            current_interruptible=current.interruptible,
            new_activity_id=new_activity.activity_id,
            new_activity_type=new_activity.activity_type.value,
            new_priority=new_activity.priority,
        )
        if not current.interruptible:
            self._trace_logger.write(
                "activity_manager:should_activate:false",
                reason="current_not_interruptible",
                current_activity_id=current.activity_id,
                new_activity_id=new_activity.activity_id,
            )
            return False

        should_activate = new_activity.priority > current.priority
        self._trace_logger.write(
            "activity_manager:should_activate:result",
            should_activate=should_activate,
            reason="new_priority_higher" if should_activate else "new_priority_not_higher",
            current_priority=current.priority,
            new_priority=new_activity.priority,
        )
        return should_activate

    def _activate(self, activity: Activity) -> Activity:
        active = activity.with_status(ActivityStatus.ACTIVE)
        self._activities[active.activity_id] = active
        self._foreground_activity_id = active.activity_id
        self._trace_logger.write(
            "activity_manager:activate",
            activity_id=active.activity_id,
            activity_type=active.activity_type.value,
            activity_priority=active.priority,
            foreground_activity_id=self._foreground_activity_id,
        )
        return active
