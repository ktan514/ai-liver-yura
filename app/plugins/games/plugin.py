from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

from app.plugins.games.activity_factory import TransientGameActivityFactory
from app.plugins.games.activity_matcher import ExactActivityPhraseMatcher
from app.plugins.games.game_engine import GameEngine
from app.plugins.games.intent import (
    GameCommandValidator,
    GameIntent,
    GameIntentCommand,
    GameIntentInterpreter,
)
from app.plugins.games.shiritori import (
    ShiritoriGameDefinition,
    ShiritoriGameService,
    ShiritoriPlayer,
    ShiritoriState,
)
from app.shared.contracts.activity import (
    ActivityDefinition,
    ActivityOperation,
    ActivityPlanView,
    BehaviorDecision,
)
from app.shared.contracts.plugins.runtime import (
    MemoryPolicy,
    PluginActivityRequest,
    PluginActivityState,
    PluginActivityStatus,
    PluginActivityWorkItem,
    PluginCapability,
    PluginCommand,
    PluginContext,
    PluginExecutionResult,
    PluginIntentResult,
)
from app.shared.observability import PluginLogger


class GamesPlugin:
    plugin_id = "games"
    display_name = "Games"
    SHIRITORI_CAPABILITY = "games.shiritori"

    def __init__(self) -> None:
        self._context: PluginContext | None = None
        self._engine: GameEngine | None = None
        self._service: ShiritoriGameService | None = None
        self._interpreter: GameIntentInterpreter | None = None
        self._validator: GameCommandValidator | None = None
        self._state_version = 0
        self._llm_available = True
        self._intent_interpreter_enabled = True
        self._trace_logger = PluginLogger(__name__)
        self._capabilities = frozenset(
            {
                *(capability.value for capability in PluginCapability),
                self.SHIRITORI_CAPABILITY,
            }
        )

    @property
    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    def available_capabilities(self) -> frozenset[str]:
        if self._engine is None:
            return frozenset()
        available = {
            PluginCapability.PROMPT_CONTEXT_PROVIDER.value,
            PluginCapability.MEMORY_POLICY_PROVIDER.value,
        }
        if self._intent_interpreter_enabled:
            available.add(PluginCapability.USER_INTENT_INTERPRETER.value)
        if self._llm_available and self._intent_interpreter_enabled:
            available.update(
                {
                    PluginCapability.COMMAND_HANDLER.value,
                    PluginCapability.ACTIVITY_PROVIDER.value,
                    self.SHIRITORI_CAPABILITY,
                }
            )
        return frozenset(available)

    def activity_definitions(self) -> tuple[ActivityDefinition, ...]:
        start_phrases = (
            "しりとりしよう",
            "しりとりしよ",
            "しりとりしたい",
            "しりとりやろう",
            "しりとりを始めて",
        )
        stop_phrases = ("しりとりをやめよう",)
        continue_phrases = ("しりとりを続けよう",)
        return (
            ActivityDefinition(
                activity_type="shiritori",
                display_name="しりとり",
                required_capability=self.SHIRITORI_CAPABILITY,
                provider_plugin_id=self.plugin_id,
                description="ユーザーと交互に単語の末尾をつなげる継続ゲーム",
                supported_operations=(
                    ActivityOperation.START,
                    ActivityOperation.CONTINUE,
                    ActivityOperation.STOP,
                ),
                semantic_descriptions=(
                    "言葉を交互につなぐ遊び",
                    "前の単語の最後の文字から次の単語を返す",
                    "テーマやカテゴリによる言葉の制約を付けて遊べる",
                ),
                constraints_schema={
                    "type": "object",
                    "properties": {
                        "theme": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 80,
                            "description": "しりとりで使用する任意のテーマ",
                        }
                    },
                    "additionalProperties": False,
                },
                constraints_schema_version="1.0",
                matchers=(
                    ExactActivityPhraseMatcher(
                        start_phrases=start_phrases,
                        stop_phrases=stop_phrases,
                        continue_phrases=continue_phrases,
                        display_name="しりとり",
                    ),
                ),
            ),
        )

    def active_activity_definition(self) -> ActivityDefinition | None:
        engine = self._engine
        if engine is None or engine.get_active_session() is None:
            return None
        return self.activity_definitions()[0]

    def initialize(self, context: PluginContext) -> None:
        self._context = context
        configuration = context.configuration
        shiritori = configuration.get("shiritori", {})
        if not isinstance(shiritori, Mapping) or not bool(
            shiritori.get("enabled", True)
        ):
            raise RuntimeError("有効なゲームがありません。")
        engine = GameEngine((ShiritoriGameDefinition(),))
        max_retries = int(shiritori.get("max_generation_retries", 3))
        self._engine = engine
        self._service = ShiritoriGameService(
            engine, max_generation_attempts=max_retries
        )
        interpreter_config = configuration.get("intent_interpreter", {})
        if not isinstance(interpreter_config, Mapping):
            interpreter_config = {}
        self._intent_interpreter_enabled = bool(interpreter_config.get("enabled", True))
        self._interpreter = GameIntentInterpreter(
            engine,
            context.llm_gateway,
            max_attempts=int(interpreter_config.get("max_attempts", 2)),
        )
        self._validator = GameCommandValidator(
            engine,
            confidence_threshold=float(
                interpreter_config.get("confidence_threshold", 0.85)
            ),
        )
        self._llm_available = bool(configuration.get("llm_available", True))
        self._trace_logger.info(
            "games_plugin:initialized",
            plugin_id=self.plugin_id,
            supported_games=[game.game_type for game in engine.list_supported_games()],
            llm_available=self._llm_available,
        )

    def shutdown(self) -> None:
        engine = self._engine
        if engine is not None and engine.get_active_session() is not None:
            engine.cancel_game("plugin_shutdown")
        self._context = None
        self._engine = None
        self._service = None
        self._interpreter = None
        self._validator = None
        self._intent_interpreter_enabled = False

    async def interpret_user_text(self, text: str) -> PluginIntentResult:
        interpreter = self._require_interpreter()
        command = await interpreter.interpret(text, state_version=self._state_version)
        handled = command.intent != GameIntent.NOT_HANDLED
        generic_command = PluginCommand(
            command_type=command.intent.value,
            operation=self._operation_for_command(command),
            payload={
                "game_type": command.game_type,
                "game_move": command.game_move,
                "chat_text": command.chat_text,
                "control": command.control,
                "constraints": dict(command.constraints),
                "confidence": command.confidence,
                "reason": command.reason,
                "classifier_type": command.classifier_type,
            },
            requires_confirmation=command.requires_confirmation,
            state_version=command.state_version,
        )
        return PluginIntentResult(
            plugin_id=self.plugin_id,
            handled=handled,
            confidence=command.confidence,
            command=generic_command if handled else None,
            reason=command.reason,
            classifier_type=command.classifier_type,
            conversation_context=self._conversation_context(command),
        )

    async def interpret_activity_plan(
        self, plan: ActivityPlanView, text: str
    ) -> PluginIntentResult:
        """検証前の意味Planを、Plugin固有Commandへ副作用なしで変換する。"""

        if (
            plan.activity_type != "shiritori"
            or plan.required_capability != self.SHIRITORI_CAPABILITY
            or plan.decision
            not in {
                BehaviorDecision.START_ACTIVITY,
                BehaviorDecision.CONTINUE_ACTIVITY,
                BehaviorDecision.SWITCH_ACTIVITY,
            }
        ):
            return PluginIntentResult(
                plugin_id=self.plugin_id,
                handled=False,
                confidence=plan.confidence,
                reason="activity_plan_not_supported",
                classifier_type="behavior_plan",
            )
        if plan.operation == ActivityOperation.START:
            intent = GameIntent.START_GAME
            control = None
        elif plan.operation == ActivityOperation.STOP:
            intent = GameIntent.GAME_CONTROL
            control = "quit"
        else:
            return await self.interpret_user_text(text)
        command = GameIntentCommand(
            intent=intent,
            game_type="shiritori",
            confidence=plan.confidence,
            state_version=self._state_version,
            control=control,
            constraints=plan.constraints,
            reason=plan.reason,
            classifier_type="behavior_plan",
        )
        generic_command = PluginCommand(
            command_type=command.intent.value,
            operation=plan.operation.value if plan.operation is not None else None,
            payload={
                "game_type": command.game_type,
                "game_move": command.game_move,
                "chat_text": command.chat_text,
                "control": command.control,
                "constraints": dict(command.constraints),
                "confidence": command.confidence,
                "reason": command.reason,
                "classifier_type": command.classifier_type,
            },
            state_version=command.state_version,
            validated_constraints=plan.validated_constraints,
        )
        return PluginIntentResult(
            plugin_id=self.plugin_id,
            handled=True,
            confidence=command.confidence,
            command=generic_command,
            reason=command.reason,
            classifier_type=command.classifier_type,
            conversation_context=self._conversation_context(command),
        )

    async def execute_command(
        self, result: PluginIntentResult
    ) -> PluginExecutionResult:
        command = self._to_game_command(result)
        validation = self._require_validator().validate(
            command, current_state_version=self._state_version
        )
        if not validation.accepted:
            return PluginExecutionResult(
                plugin_id=self.plugin_id,
                handled=False,
                conversation_context={
                    **self._conversation_context(command),
                    **self._public_session_context(),
                    "plugin_command_rejected": True,
                    "requires_confirmation": validation.requires_confirmation,
                    "rejection_reason": validation.reason,
                },
                reason=validation.reason,
            )
        try:
            execution = await self._execute_validated(command)
        except Exception as error:
            self._trace_logger.error(
                "game_command_router:execution_failed",
                intent=command.intent.value,
                game_type=command.game_type,
                state_version=command.state_version,
                error_type=type(error).__name__,
            )
            engine = self._require_engine()
            if engine.get_active_session() is not None:
                engine.cancel_game("plugin_command_execution_failed")
                self._state_version += 1
            session_context = self._public_session_context()
            return PluginExecutionResult(
                plugin_id=self.plugin_id,
                handled=False,
                conversation_context={
                    **self._conversation_context(command),
                    **session_context,
                    "plugin_command_failed": True,
                },
                reason="command_execution_failed",
                unavailable_capabilities=frozenset(
                    {
                        PluginCapability.COMMAND_HANDLER.value,
                        PluginCapability.ACTIVITY_PROVIDER.value,
                    }
                ),
                activity_state=self._activity_state(),
            )
        self._trace_logger.info(
            "game_command_router:routed",
            intent=command.intent.value,
            game_type=command.game_type,
            state_version=self._state_version,
        )
        return execution

    def snapshot(self) -> Mapping[str, object]:
        engine = self._engine
        session = engine.get_current_session() if engine else None
        state = session.metadata.get("shiritori_state") if session else None
        return {
            "initialized": engine is not None,
            "state_version": self._state_version,
            "session_id": session.session_id if session else None,
            "session_status": session.status.value if session else None,
            "game_type": session.game_type if session else None,
            "ongoing_activity_id": (
                session.metadata.get("ongoing_activity_id") if session else None
            ),
            "game_state": asdict(state) if isinstance(state, ShiritoriState) else None,
        }

    def link_ongoing_activity(self, ongoing_activity_id: str) -> Mapping[str, object]:
        session = self._require_engine().link_ongoing_activity(ongoing_activity_id)
        return {
            "session_id": session.session_id,
            "game_type": session.game_type,
            "ongoing_activity_id": ongoing_activity_id,
        }

    def rollback_active_session(self, reason: str) -> None:
        engine = self._require_engine()
        if engine.get_active_session() is not None:
            engine.cancel_game(reason)
            self._state_version += 1
            self._trace_logger.warning(
                "games_plugin:session_rolled_back",
                reason=reason,
            )

    async def _execute_validated(
        self, command: GameIntentCommand
    ) -> PluginExecutionResult:
        if command.intent in {
            GameIntent.NORMAL_CHAT,
            GameIntent.GAME_CHAT,
            GameIntent.AMBIGUOUS,
            GameIntent.UNSUPPORTED_GAME_REQUEST,
            GameIntent.MIXED,
        }:
            return PluginExecutionResult(
                plugin_id=self.plugin_id,
                handled=False,
                conversation_context=self._conversation_context(command),
                reason=command.reason,
            )
        if command.intent == GameIntent.START_GAME:
            if not self._llm_available:
                return PluginExecutionResult(
                    plugin_id=self.plugin_id,
                    handled=False,
                    conversation_context={
                        **self._conversation_context(command),
                        "game_provider_unavailable": True,
                    },
                    reason="game_llm_provider_unavailable",
                )
            _, activity = self._require_service().start_game(
                TransientGameActivityFactory(),
                started_by=ShiritoriPlayer.AI,
                constraints=dict(command.constraints),
            )
            response_text = await self._require_service().generate_ai_turn(
                activity, self._require_context().llm_gateway
            )
            self._state_version += 1
            return self._activity_result(response_text, activity)
        if command.intent == GameIntent.PLAY_GAME_MOVE:
            _, activity = self._require_service().submit_user_word(
                TransientGameActivityFactory(),
                command.game_move or "",
            )
            if activity.context.get("shiritori_action") == "generate_ai_word":
                response_text = await self._require_service().generate_ai_turn(
                    activity, self._require_context().llm_gateway
                )
            else:
                response_text = (
                    await self._require_context().llm_gateway.generate_response(
                        activity
                    )
                )
            self._state_version += 1
            return self._activity_result(response_text, activity)
        if command.intent == GameIntent.GAME_CONTROL:
            engine = self._require_engine()
            if command.control == "pause":
                engine.pause_game(reason="plugin_command")
                response_text = "ゲームを一時停止したよ。"
            elif command.control == "resume":
                engine.resume_game(reason="plugin_command")
                response_text = "ゲームを再開するね。"
            elif command.control == "quit":
                engine.cancel_game("plugin_command_quit")
                response_text = "ゲームを終了したよ。"
            else:
                activity = self._require_service().surrender(
                    TransientGameActivityFactory(),
                    player=ShiritoriPlayer.USER,
                )
                response_text = (
                    await self._require_context().llm_gateway.generate_response(
                        activity
                    )
                )
            self._state_version += 1
            context = self._public_session_context()
            state = self._require_activity_state()
            return PluginExecutionResult(
                plugin_id=self.plugin_id,
                handled=True,
                activity_request=PluginActivityRequest(
                    plugin_id=self.plugin_id,
                    activity_kind="game_with_user",
                    priority=100,
                    context=context,
                    response_text=response_text,
                    state=state,
                    memory_policy=MemoryPolicy(True, True, True),
                ),
                activity_state=state,
            )
        return PluginExecutionResult(self.plugin_id, False, reason="not_handled")

    def _activity_result(
        self, response_text: str, source_activity: PluginActivityWorkItem
    ) -> PluginExecutionResult:
        state = self._require_activity_state()
        return PluginExecutionResult(
            plugin_id=self.plugin_id,
            handled=True,
            activity_request=PluginActivityRequest(
                plugin_id=self.plugin_id,
                activity_kind="game_with_user",
                priority=source_activity.priority,
                context={**source_activity.context, **self._public_session_context()},
                response_text=response_text,
                state=state,
                memory_policy=MemoryPolicy(True, True, True),
            ),
            activity_state=state,
        )

    def _activity_state(self) -> PluginActivityState | None:
        engine = self._engine
        session = engine.get_current_session() if engine is not None else None
        if session is None:
            return None
        status = {
            "playing": PluginActivityStatus.WAITING_INPUT,
            "paused": PluginActivityStatus.SUSPENDED,
            "completed": PluginActivityStatus.COMPLETED,
            "canceled": PluginActivityStatus.CANCELED,
        }.get(session.status.value)
        if status is None:
            return None
        return PluginActivityState(
            session_id=session.session_id,
            status=status,
            expected_input=(
                "次の単語または操作"
                if status == PluginActivityStatus.WAITING_INPUT
                else ""
            ),
            end_condition="しりとり終了またはユーザーによる停止",
        )

    def _require_activity_state(self) -> PluginActivityState:
        state = self._activity_state()
        if state is None:
            raise RuntimeError("Games PluginのActivity状態がありません。")
        return state

    def _public_session_context(self) -> dict[str, object]:
        engine = self._require_engine()
        session = engine.get_current_session()
        state = session.metadata.get("shiritori_state") if session else None
        return {
            "plugin_id": self.plugin_id,
            "plugin_state_version": self._state_version,
            "session_id": session.session_id if session else None,
            "session_status": session.status.value if session else None,
            "game_type": session.game_type if session else None,
            "ongoing_activity_id": (
                session.metadata.get("ongoing_activity_id") if session else None
            ),
            "game_state": asdict(state) if isinstance(state, ShiritoriState) else None,
        }

    def _conversation_context(self, command: GameIntentCommand) -> dict[str, object]:
        engine = self._engine
        session = engine.get_active_session() if engine else None
        return {
            "plugin_id": self.plugin_id,
            "plugin_intent": command.intent.value,
            "plugin_state_version": command.state_version,
            "game_session_active": session is not None,
            "game_type": session.game_type if session else command.game_type,
            "game_move": command.game_move,
            "chat_text": command.chat_text,
            "control": command.control,
            "activity_constraints": dict(command.constraints),
            "execution_requested": command.intent
            in {
                GameIntent.START_GAME,
                GameIntent.PLAY_GAME_MOVE,
                GameIntent.GAME_CONTROL,
            },
            "execution_performed": False,
        }

    @staticmethod
    def _operation_for_command(command: GameIntentCommand) -> str | None:
        if command.intent == GameIntent.START_GAME:
            return "start"
        if command.intent == GameIntent.PLAY_GAME_MOVE:
            return "continue"
        if command.intent == GameIntent.GAME_CONTROL:
            if command.control == "quit":
                return "stop"
            if command.control in {"pause", "resume", "surrender"}:
                return command.control
            return "continue"
        return None

    def _to_game_command(self, result: PluginIntentResult) -> GameIntentCommand:
        command = result.command
        if command is None:
            raise ValueError("PluginCommandがありません。")
        payload = command.payload
        confidence_value = payload.get("confidence", result.confidence)
        confidence = (
            float(confidence_value)
            if isinstance(confidence_value, (int, float, str))
            else result.confidence
        )
        constraints_value = (
            command.validated_constraints
            if command.validated_constraints is not None
            else payload.get("constraints", {})
        )
        constraints = (
            dict(constraints_value) if isinstance(constraints_value, Mapping) else {}
        )
        return GameIntentCommand(
            intent=GameIntent(command.command_type),
            game_type=self._optional_str(payload.get("game_type")),
            confidence=confidence,
            state_version=(
                command.state_version if command.state_version is not None else -1
            ),
            game_move=self._optional_str(payload.get("game_move")),
            chat_text=self._optional_str(payload.get("chat_text")),
            control=self._optional_str(payload.get("control")),
            constraints=constraints,
            requires_confirmation=command.requires_confirmation,
            reason=str(payload.get("reason") or result.reason),
            classifier_type=str(
                payload.get("classifier_type") or result.classifier_type
            ),
        )

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    def _require_context(self) -> PluginContext:
        if self._context is None:
            raise RuntimeError("Games Pluginが初期化されていません。")
        return self._context

    def _require_engine(self) -> GameEngine:
        if self._engine is None:
            raise RuntimeError("GameEngineが利用できません。")
        return self._engine

    def _require_service(self) -> ShiritoriGameService:
        if self._service is None:
            raise RuntimeError("ShiritoriGameServiceが利用できません。")
        return self._service

    def _require_interpreter(self) -> GameIntentInterpreter:
        if self._interpreter is None:
            raise RuntimeError("GameIntentInterpreterが利用できません。")
        return self._interpreter

    def _require_validator(self) -> GameCommandValidator:
        if self._validator is None:
            raise RuntimeError("GameCommandValidatorが利用できません。")
        return self._validator
