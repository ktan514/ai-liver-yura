import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.adapters.embedding.openai_embedding_generator import OpenAIEmbeddingGenerator
from app.adapters.storage.postgres_topic_memory_store import PostgresTopicMemoryStore
from app.adapters.topic.llm_topic_classifier import LlmTopicClassifier
from app.adapters.tts import SystemAudioPlayer, VoiceVoxSpeechSynthesizer
from app.bootstrap.runtime import (
    create_audio_player,
    create_embedding_generator,
    create_runtime_coordinator,
    create_speech_synthesizer,
    create_topic_classifier,
    create_topic_memory_store,
)
from app.config.app_config import AppConfig, load_app_config
from app.core.plugins import PluginCapability
from app.domain.activities import Activity, ActivityType
from app.domain.behavior import BehaviorDecision
from app.plugins.games import GamesPlugin
from app.ports.response_generator import ResponseGenerator
from app.runtime import RuntimeCoordinator


class FactoryShiritoriResponseGenerator(ResponseGenerator):
    def __init__(self) -> None:
        self._responses = iter(
            [
                '{"game_action":"play_word","word":"うみ","utterance":"うみ！"}',
                '{"game_action":"play_word","word":"ずこう","utterance":"ずこう！"}',
                '{"game_action":"play_word","word":"ぎんこう","utterance":"ぎんこう！"}',
                '{"game_action":"play_word","word":"しまうま","utterance":"しまうま！"}',
            ]
        )
        self.game_call_count = 0
        self.conversation_call_count = 0
        self.behavior_call_count = 0
        self.last_game_context: dict[str, object] | None = None

    async def generate_response(self, activity: Activity) -> str:
        if activity.activity_type == ActivityType.BEHAVIOR_PLANNING:
            self.behavior_call_count += 1
            text = str(activity.context.get("user_input") or "")
            planner_state = activity.context.get("planner_state")
            ongoing = (
                planner_state.get("ongoing_activity")
                if isinstance(planner_state, dict)
                else None
            )
            if isinstance(ongoing, dict) and text in {
                "みみず",
                "うさぎ",
                "うし",
                "みかん",
            }:
                return json.dumps(
                    {
                        "decision": "continue_activity",
                        "activity_type": "shiritori",
                        "operation": "continue",
                        "goal": "しりとりの次の単語を処理する",
                        "constraints": {},
                        "speech_act": "statement",
                        "negated": False,
                        "hypothetical": False,
                        "past_reference": False,
                        "knowledge_question": False,
                        "confidence": 0.99,
                        "reason": "expected_game_input",
                        "ongoing_input_decision": "continue_current",
                    },
                    ensure_ascii=False,
                )
            if isinstance(ongoing, dict):
                ongoing_cases: dict[str, dict[str, object]] = {
                    "もう終わりにしよう": {
                        "activity_type": "shiritori",
                        "operation": "stop",
                        "goal": "進行中のしりとりを終了する",
                        "ongoing_input_decision": "stop_current",
                        "confidence": 0.96,
                    },
                    "このしりとりって何文字まで使えるの？": {
                        "activity_type": "conversation",
                        "operation": "discuss",
                        "goal": "進行中のしりとりのルールについて答える",
                        "ongoing_input_decision": "conversation_about_current",
                        "confidence": 0.96,
                    },
                    "ところで深海魚って光るの？": {
                        "activity_type": "conversation",
                        "operation": "discuss",
                        "goal": "深海魚について会話する",
                        "ongoing_input_decision": "conversation_unrelated",
                        "confidence": 0.96,
                    },
                    "それはもういいかな": {
                        "activity_type": "conversation",
                        "operation": None,
                        "goal": "意図を確認する",
                        "ongoing_input_decision": "ask_confirmation",
                        "confidence": 0.4,
                    },
                    "ちょっと待って": {
                        "activity_type": "shiritori",
                        "operation": "continue",
                        "goal": "進行中のしりとりを一時停止する",
                        "ongoing_input_decision": "pause_current",
                        "confidence": 0.96,
                    },
                    "再開しよう": {
                        "activity_type": "shiritori",
                        "operation": "continue",
                        "goal": "一時停止中のしりとりを再開する",
                        "ongoing_input_decision": "resume_current",
                        "confidence": 0.96,
                    },
                    "昨日は途中でやめたよね": {
                        "activity_type": "conversation",
                        "operation": "discuss",
                        "goal": "過去の中断について会話する",
                        "ongoing_input_decision": "conversation_about_current",
                        "confidence": 0.96,
                        "past_reference": True,
                    },
                }
                case = ongoing_cases.get(text)
                if case is not None:
                    return json.dumps(
                        {
                            "decision": "conversation",
                            "constraints": {},
                            "speech_act": "question",
                            "negated": False,
                            "hypothetical": False,
                            "past_reference": False,
                            "knowledge_question": False,
                            "reason": "test_ongoing_semantics",
                            **case,
                        },
                        ensure_ascii=False,
                    )
            start_requested = any(
                marker in text
                for marker in ("しりとり", "語尾をつないで", "最後の文字から")
            ) and not any(
                marker in text
                for marker in (
                    "って何",
                    "ルール",
                    "難しい",
                    "昨日",
                    "したくない",
                    "としたら",
                )
            )
            theme = next(
                (
                    value
                    for marker, value in (
                        ("深海生物", "深海生物"),
                        ("動物", "動物"),
                        ("食べ物", "食べ物"),
                    )
                    if marker in text
                ),
                None,
            )
            return json.dumps(
                {
                    "decision": "start_activity" if start_requested else "conversation",
                    "activity_type": "shiritori" if start_requested else "conversation",
                    "operation": "start" if start_requested else "discuss",
                    "goal": (
                        "条件に沿ってしりとりを行う"
                        if start_requested
                        else "通常会話で応答する"
                    ),
                    "constraints": {"theme": theme} if theme else {},
                    "speech_act": "proposal" if start_requested else "request",
                    "negated": False,
                    "hypothetical": False,
                    "past_reference": False,
                    "knowledge_question": False,
                    "confidence": 0.95,
                    "reason": "test_semantic_result",
                },
                ensure_ascii=False,
            )
        if activity.activity_type == ActivityType.PLUGIN_ACTIVITY:
            self.game_call_count += 1
            self.last_game_context = dict(activity.context)
            return next(self._responses)
        self.conversation_call_count += 1
        return "通常会話"


class LowConfidenceStartResponseGenerator(FactoryShiritoriResponseGenerator):
    async def generate_response(self, activity: Activity) -> str:
        if (
            activity.activity_type == ActivityType.BEHAVIOR_PLANNING
            and activity.context.get("user_input") == "言葉をつなぐ遊びをやらない？"
        ):
            self.behavior_call_count += 1
            return json.dumps(
                {
                    "decision": "start_activity",
                    "activity_type": "shiritori",
                    "operation": "start",
                    "goal": "言葉をつなぐ遊びを始める",
                    "constraints": {"theme": "海の生き物"},
                    "speech_act": "proposal",
                    "negated": False,
                    "hypothetical": False,
                    "past_reference": False,
                    "knowledge_question": False,
                    "confidence": 0.6,
                    "reason": "low_confidence_start",
                },
                ensure_ascii=False,
            )
        return await super().generate_response(activity)


class InvalidConstraintResponseGenerator(FactoryShiritoriResponseGenerator):
    async def generate_response(self, activity: Activity) -> str:
        if (
            activity.activity_type == ActivityType.BEHAVIOR_PLANNING
            and activity.context.get("user_input") == "不正なテーマで言葉遊び"
        ):
            self.behavior_call_count += 1
            return json.dumps(
                {
                    "decision": "start_activity",
                    "activity_type": "shiritori",
                    "operation": "start",
                    "goal": "しりとりを開始する",
                    "constraints": {"theme": ["invalid"]},
                    "speech_act": "request",
                    "negated": False,
                    "hypothetical": False,
                    "past_reference": False,
                    "knowledge_question": False,
                    "confidence": 0.99,
                    "reason": "invalid_constraint_test",
                },
                ensure_ascii=False,
            )
        return await super().generate_response(activity)


class FailingFactoryResponseGenerator(ResponseGenerator):
    async def generate_response(self, activity: Activity) -> str:
        raise RuntimeError("provider unavailable")


def _required_env_name(value: str | None) -> str:
    assert value is not None
    return value


def _openai_api_key_env(config: AppConfig) -> str:
    return _required_env_name(config.services["openai"].api_key_env)


def _database_dsn_env(config: AppConfig) -> str:
    service = config.services[config.memory.topic_memory.database_service]
    return _required_env_name(service.dsn_env)


def _games_test_config() -> AppConfig:
    config = load_app_config()
    return replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=True)
        ),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
    )


def test_create_voicevox_speech_components() -> None:
    config = load_app_config()

    synthesizer = create_speech_synthesizer(config)
    player = create_audio_player(config)

    assert isinstance(synthesizer, VoiceVoxSpeechSynthesizer)
    assert isinstance(player, SystemAudioPlayer)


def test_trace_detail_settings_are_loaded_from_config() -> None:
    trace = load_app_config().trace

    assert trace.level == "INFO"
    assert trace.timezone == "local"
    assert trace.debug_file_enabled is True
    assert trace.debug_file_path == "logs/runtime_debug.log"
    assert trace.log_llm_prompts is True
    assert trace.log_llm_responses is True
    assert trace.log_user_input is True


def test_create_speech_components_returns_none_when_disabled() -> None:
    config = load_app_config()
    config = replace(config, speech=replace(config.speech, enabled=False))

    assert create_speech_synthesizer(config) is None
    assert create_audio_player(config) is None


def test_legacy_runtime_factory_module_reexports_bootstrap_factory() -> None:
    from app.runtime.runtime_factory import (
        create_runtime_coordinator as compatibility_factory,
    )

    assert compatibility_factory is create_runtime_coordinator


def test_create_runtime_coordinator_returns_runtime_coordinator() -> None:
    config = load_app_config()
    config = replace(
        config,
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=True)
        ),
    )

    runtime = create_runtime_coordinator(config)

    assert isinstance(runtime, RuntimeCoordinator)
    assert runtime.plugin_manager is not None
    assert runtime.plugin_manager.get_plugin("games") is not None
    assert runtime.plugin_manager.get_plugin("voice_output") is not None
    assert runtime.plugin_manager.is_capability_available(
        "output.speech", "voice_output"
    )
    diagnostic = runtime.diagnostic_snapshot()
    plugins = diagnostic["plugins"]
    assert isinstance(plugins, dict)
    assert plugins["statuses"] == {
        "llm_provider.default": "initialized",
        "llm_provider.situation_evaluator": "initialized",
        "llm_provider.character": "initialized",
        "llm_provider.response_validator": "initialized",
        "games": "initialized",
        "agent_memory": "disabled",
        "relationship_memory": "disabled",
        "voice_output": "initialized",
    }
    assert "output.speech" in plugins["available_capabilities"]


@pytest.mark.asyncio
async def test_runtime_factory_persists_and_restores_relationship_memory(
    tmp_path: Path,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=False)
        ),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
            relationship_memory=replace(
                config.memory.relationship_memory,
                enabled=True,
                path=str(tmp_path / "relationships.json"),
            ),
        ),
    )
    runtime = create_runtime_coordinator(config)

    await runtime.submit_user_text("こんにちは", source="console")

    restored = create_runtime_coordinator(config)
    current = restored.agent_state.relationship_memory.current
    assert current is not None
    assert current.counterpart_id == "local:user"
    assert current.interaction_count == 1
    assert restored.plugin_manager is not None
    assert restored.plugin_manager.is_capability_available(
        "memory.relationship", "relationship_memory"
    )


@pytest.mark.asyncio
async def test_production_factory_public_input_keeps_same_shiritori_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=True)
        ),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
    )
    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory,
        "create_response_generator",
        lambda **_: generator,
    )
    runtime = runtime_factory.create_runtime_coordinator(config)
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)

    await runtime.submit_user_text("しりとりしよ", source="console")
    first = games.snapshot()
    assert runtime.last_behavior_evaluation is not None
    assert runtime.last_behavior_evaluation.accepted is True
    assert runtime.last_behavior_evaluation.plan.activity_type == "shiritori"
    assert (
        runtime.last_behavior_evaluation.plan.decision
        == BehaviorDecision.START_ACTIVITY
    )
    session_id = first["session_id"]
    ongoing = runtime.activity_manager.ongoing_activity
    assert ongoing is not None
    assert ongoing.activity_type == "shiritori"
    ongoing_activity_id = ongoing.ongoing_activity_id
    assert ongoing.context["plugin_session_id"] == session_id
    assert runtime.agent_state.relationship_memory.current is not None
    assert runtime.agent_state.relationship_memory.current.interaction_count == 1
    assert first["ongoing_activity_id"] == ongoing_activity_id
    assert len(ongoing.turns) == 1
    assert ongoing.status.value == "waiting"
    first_state = first["game_state"]
    assert isinstance(first_state, dict)
    assert first_state["last_word"] == "うみ"
    assert first_state["expected_head"] == "み"

    await runtime.submit_user_text("みみず", source="console")
    await runtime.submit_user_text("うさぎ", source="console")
    await runtime.submit_user_text("うし", source="console")

    final = games.snapshot()
    state = final["game_state"]
    assert isinstance(state, dict)
    assert final["session_id"] == session_id
    final_ongoing = runtime.activity_manager.ongoing_activity
    assert final_ongoing is not None
    assert final_ongoing.ongoing_activity_id == ongoing_activity_id
    assert final_ongoing.context["plugin_session_id"] == session_id
    assert runtime.agent_state.relationship_memory.current is not None
    assert runtime.agent_state.relationship_memory.current.interaction_count == 4
    assert len(final_ongoing.turns) == 4
    assert all(turn.execution_result is not None for turn in final_ongoing.turns)
    assert final_ongoing.status.value == "waiting"
    assert state["used_words"] == (
        "うみ",
        "みみず",
        "ずこう",
        "うさぎ",
        "ぎんこう",
        "うし",
        "しまうま",
    )
    assert getattr(state["current_turn"], "value", None) == "user"
    assert state["expected_head"] == "ま"
    assert generator.game_call_count == 4
    assert generator.conversation_call_count == 0


@pytest.mark.asyncio
async def test_semantic_activity_constraints_reach_enabled_games_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=True)
        ),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
    )
    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(config)

    await runtime.submit_user_text(
        "深海生物縛りでしりとりしませんか？", source="console"
    )

    evaluation = runtime.last_behavior_evaluation
    assert evaluation is not None
    assert evaluation.accepted is True
    assert evaluation.plan.activity_type == "shiritori"
    assert evaluation.plan.operation is not None
    assert evaluation.plan.operation.value == "start"
    assert evaluation.plan.constraints == {"theme": "深海生物"}
    assert generator.behavior_call_count == 1
    assert generator.game_call_count == 1
    assert generator.last_game_context is not None
    assert generator.last_game_context["activity_constraints"] == {"theme": "深海生物"}
    assert "深海生物" in str(generator.last_game_context["plugin_prompt_override"])
    ongoing = runtime.activity_manager.ongoing_activity
    assert ongoing is not None
    assert ongoing.context["constraints"] == {"theme": "深海生物"}

    await runtime.submit_user_text("みみず", source="console")

    continued = runtime.activity_manager.ongoing_activity
    assert continued is not None
    assert continued.context["constraints"] == {"theme": "深海生物"}
    assert continued.turns[-1].constraints_snapshot == {"theme": "深海生物"}


@pytest.mark.asyncio
async def test_semantic_start_is_rejected_without_games_plugin_and_no_first_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=False)
        ),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
    )
    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(config)

    await runtime.submit_user_text(
        "深海生物縛りでしりとりしませんか？", source="console"
    )
    group = await runtime.run_once()

    evaluation = runtime.last_behavior_evaluation
    assert evaluation is not None
    assert evaluation.plan.activity_type == "shiritori"
    assert evaluation.plan.constraints == {"theme": "深海生物"}
    assert evaluation.accepted is False
    assert evaluation.result.data["reason"] == "capability_unavailable"
    assert runtime.activity_manager.ongoing_activity is None
    assert generator.game_call_count == 0
    assert group is not None
    spoken = [
        action.text
        for action in group.action_plans
        if action.action_type.value == "speak"
    ]
    assert spoken == ["今はそれを一緒にできないんだ。別のお話をしよう。"]
    assert all("りんご" not in text for text in spoken)


@pytest.mark.asyncio
async def test_games_plugin_disabled_keeps_core_conversation_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins,
            games=replace(config.plugins.games, enabled=False),
        ),
    )
    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(config)

    await runtime.submit_user_text("しりとりしよう", source="console")
    group = await runtime.run_once()

    assert runtime.plugin_manager is not None
    assert runtime.plugin_manager.get_plugin("games") is None
    assert runtime.last_behavior_evaluation is not None
    assert runtime.last_behavior_evaluation.plan.activity_type == "shiritori"
    assert runtime.last_behavior_evaluation.accepted is False
    assert runtime.last_behavior_fallback_plan is not None
    assert runtime.last_behavior_fallback_plan.decision == BehaviorDecision.CONVERSATION
    assert group is not None
    assert generator.game_call_count == 0
    assert generator.conversation_call_count == 0
    assert all("りんご" not in plan.text for plan in group.action_plans)


@pytest.mark.asyncio
async def test_explicit_game_stop_cancels_session_and_ongoing_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)

    await runtime.submit_user_text("しりとりしよう", source="console")
    ongoing = runtime.activity_manager.ongoing_activity
    assert ongoing is not None
    ongoing_activity_id = ongoing.ongoing_activity_id

    await runtime.submit_user_text("しりとりをやめよう", source="console")

    assert games.snapshot()["session_status"] == "canceled"
    assert runtime.activity_manager.ongoing_activity is None
    terminal = runtime.activity_manager.ongoing_activity_history[-1]
    assert terminal.ongoing_activity_id == ongoing_activity_id
    assert terminal.status.value == "canceled"
    assert len(terminal.turns) == 2


@pytest.mark.asyncio
async def test_paraphrased_stop_is_semantically_evaluated_and_stops_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())

    await runtime.submit_user_text("しりとりしよう", source="console")
    await runtime.submit_user_text("もう終わりにしよう", source="console")

    assert runtime.last_behavior_evaluation is not None
    assert runtime.last_behavior_evaluation.plan.ongoing_input_decision is not None
    assert (
        runtime.last_behavior_evaluation.plan.ongoing_input_decision.value
        == "stop_current"
    )
    assert runtime.activity_manager.ongoing_activity is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_decision"),
    [
        ("このしりとりって何文字まで使えるの？", "conversation_about_current"),
        ("ところで深海魚って光るの？", "conversation_unrelated"),
        ("しりとりをやめるとしたらどうなる？", "conversation_about_current"),
        ("昨日は途中でやめたよね", "conversation_about_current"),
    ],
)
async def test_conversation_during_game_preserves_current_without_plugin_continue(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    expected_decision: str,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)

    await runtime.submit_user_text("しりとりしよう", source="console")
    before = games.snapshot()
    ongoing = runtime.activity_manager.ongoing_activity
    assert ongoing is not None
    ongoing_id = ongoing.ongoing_activity_id
    game_calls = generator.game_call_count

    await runtime.submit_user_text(text, source="console")
    group = await runtime.run_once()

    assert group is not None
    assert runtime.last_behavior_evaluation is not None
    plan = runtime.last_behavior_evaluation.plan
    assert plan.decision == BehaviorDecision.CONVERSATION
    assert plan.ongoing_input_decision is not None
    assert plan.ongoing_input_decision.value == expected_decision
    assert plan.current_activity_preserved is True
    current = runtime.activity_manager.ongoing_activity
    assert current is not None
    assert current.ongoing_activity_id == ongoing_id
    assert games.snapshot()["game_state"] == before["game_state"]
    assert generator.game_call_count == game_calls


@pytest.mark.asyncio
async def test_negated_stop_does_not_stop_current_game(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())

    await runtime.submit_user_text("しりとりしよう", source="console")
    ongoing = runtime.activity_manager.ongoing_activity
    assert ongoing is not None
    await runtime.submit_user_text("まだやめたくない", source="console")

    assert runtime.last_behavior_evaluation is not None
    plan = runtime.last_behavior_evaluation.plan
    assert plan.ongoing_input_decision is not None
    assert plan.ongoing_input_decision.value == "continue_current"
    current = runtime.activity_manager.ongoing_activity
    assert current is not None
    assert current.ongoing_activity_id == ongoing.ongoing_activity_id


@pytest.mark.asyncio
async def test_ambiguous_ongoing_input_asks_confirmation_without_plugin_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())

    await runtime.submit_user_text("しりとりしよう", source="console")
    ongoing = runtime.activity_manager.ongoing_activity
    assert ongoing is not None
    game_calls = generator.game_call_count
    await runtime.submit_user_text("それはもういいかな", source="console")
    group = await runtime.run_once()

    assert group is not None
    assert runtime.last_behavior_evaluation is not None
    plan = runtime.last_behavior_evaluation.plan
    assert plan.decision == BehaviorDecision.ASK_CONFIRMATION
    assert plan.ongoing_input_decision is not None
    assert plan.ongoing_input_decision.value == "ask_confirmation"
    pending = runtime.pending_confirmation
    assert pending is not None
    assert pending.current_ongoing_activity_id == ongoing.ongoing_activity_id
    assert pending.attempt_count == 0
    assert generator.game_call_count == game_calls
    current = runtime.activity_manager.ongoing_activity
    assert current is not None
    assert current.ongoing_activity_id == ongoing.ongoing_activity_id


@pytest.mark.asyncio
async def test_affirmative_confirmation_revalidates_and_executes_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = LowConfidenceStartResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())

    await runtime.submit_user_text("言葉をつなぐ遊びをやらない？", source="console")

    pending = runtime.pending_confirmation
    assert pending is not None
    assert pending.candidate_activity_type == "shiritori"
    assert pending.candidate_operation == "start"
    assert pending.candidate_constraints == {"theme": "海の生き物"}
    assert runtime.activity_manager.ongoing_activity is None
    await runtime.submit_user_text("それでお願い", source="console")

    assert runtime.pending_confirmation is None
    assert runtime.last_behavior_evaluation is not None
    assert runtime.last_behavior_evaluation.accepted is True
    ongoing = runtime.activity_manager.ongoing_activity
    assert ongoing is not None
    assert ongoing.context["constraints"] == {"theme": "海の生き物"}


@pytest.mark.asyncio
async def test_affirmative_confirmation_is_rejected_when_capability_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = LowConfidenceStartResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    config = _games_test_config()
    config = replace(
        config,
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=False)
        ),
    )
    runtime = runtime_factory.create_runtime_coordinator(config)
    await runtime.submit_user_text("言葉をつなぐ遊びをやらない？", source="console")
    assert runtime.pending_confirmation is not None

    await runtime.submit_user_text("はい", source="console")

    assert runtime.pending_confirmation is None
    assert runtime.last_behavior_evaluation is not None
    assert runtime.last_behavior_evaluation.accepted is False
    assert runtime.activity_manager.ongoing_activity is None


@pytest.mark.asyncio
async def test_invalid_constraints_create_confirmation_without_calling_plugin_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = InvalidConstraintResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())

    await runtime.submit_user_text("不正なテーマで言葉遊び", source="console")

    pending = runtime.pending_confirmation
    assert pending is not None
    assert pending.confirmation_type.value == "confirm_constraints"
    assert pending.candidate_plan.constraint_errors[0].path == "theme"
    assert generator.game_call_count == 0
    assert runtime.activity_manager.ongoing_activity is None


@pytest.mark.asyncio
async def test_negative_confirmation_keeps_ongoing_activity_without_plugin_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    await runtime.submit_user_text("しりとりしよう", source="console")
    ongoing = runtime.activity_manager.ongoing_activity
    assert ongoing is not None
    await runtime.submit_user_text("それはもういいかな", source="console")
    game_calls = generator.game_call_count

    await runtime.submit_user_text("いいえ", source="console")

    assert runtime.pending_confirmation is None
    assert generator.game_call_count == game_calls
    current = runtime.activity_manager.ongoing_activity
    assert current is not None
    assert current.ongoing_activity_id == ongoing.ongoing_activity_id


@pytest.mark.asyncio
async def test_pause_and_resume_synchronize_game_and_ongoing_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)

    await runtime.submit_user_text("しりとりしよう", source="console")
    await runtime.submit_user_text("ちょっと待って", source="console")

    paused = runtime.activity_manager.ongoing_activity
    assert paused is not None
    assert paused.status.value == "suspended"
    assert games.snapshot()["session_status"] == "paused"

    await runtime.submit_user_text("再開しよう", source="console")

    resumed = runtime.activity_manager.ongoing_activity
    assert resumed is not None
    assert resumed.ongoing_activity_id == paused.ongoing_activity_id
    assert resumed.status.value == "waiting"
    assert games.snapshot()["session_status"] == "playing"


@pytest.mark.asyncio
async def test_switch_does_not_start_target_when_current_stop_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory
    from app.domain.behavior import (
        ActivityOperation,
        ActivityPlan,
        BehaviorPlanningContext,
        OngoingInputDecision,
    )
    from app.domain.events import AgentEvent, AgentEventType

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    await runtime.submit_user_text("しりとりしよう", source="console")
    assert runtime.plugin_manager is not None
    current_definition = runtime.plugin_manager.active_activity_definition()
    assert current_definition is not None
    ongoing = runtime.activity_manager.ongoing_activity
    assert ongoing is not None
    calls: list[str | None] = []

    async def fail_to_stop(
        event: AgentEvent,
        *,
        plugin_id: str | None = None,
        required_capability: str | None = None,
        activity_plan: ActivityPlan | None = None,
    ) -> AgentEvent:
        calls.append(
            activity_plan.operation.value
            if activity_plan and activity_plan.operation
            else None
        )
        return event

    monkeypatch.setattr(runtime, "_route_plugin_user_input", fail_to_stop)
    target_plan = ActivityPlan(
        decision=BehaviorDecision.SWITCH_ACTIVITY,
        activity_type="quiz",
        goal="クイズへ切り替える",
        required_capability="games.quiz",
        provider_plugin_id="quiz_plugin",
        operation=ActivityOperation.START,
        ongoing_input_decision=OngoingInputDecision.SWITCH_ACTIVITY,
        current_activity_type="shiritori",
        requested_new_activity="quiz",
    )
    context = BehaviorPlanningContext(
        user_text="しりとりはやめてクイズにしよう",
        source_event_id="switch-event",
        available_capabilities=frozenset({"games.shiritori", "games.quiz"}),
        activity_definitions=(current_definition,),
        active_activity_definition=current_definition,
        ongoing_activity_type="shiritori",
    )

    routed = await runtime._route_activity_switch(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": context.user_text},
        ),
        target_plan,
        context,
    )

    assert routed is not None
    assert calls == ["stop"]
    assert runtime.activity_manager.ongoing_activity is not None


@pytest.mark.asyncio
async def test_switch_starts_target_only_after_current_stop_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory
    from app.domain.behavior import (
        ActivityOperation,
        ActivityPlan,
        BehaviorPlanningContext,
        OngoingInputDecision,
    )
    from app.domain.events import AgentEvent, AgentEventType

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    await runtime.submit_user_text("しりとりしよう", source="console")
    assert runtime.plugin_manager is not None
    current_definition = runtime.plugin_manager.active_activity_definition()
    assert current_definition is not None
    calls: list[str | None] = []

    async def route_switch_step(
        event: AgentEvent,
        *,
        plugin_id: str | None = None,
        required_capability: str | None = None,
        activity_plan: ActivityPlan | None = None,
    ) -> AgentEvent | None:
        operation = (
            activity_plan.operation.value
            if activity_plan and activity_plan.operation
            else None
        )
        calls.append(operation)
        if operation == "stop":
            runtime.activity_manager.cancel_ongoing_activity(reason="test_switch_stop")
        elif operation == "start":
            runtime.activity_manager.start_ongoing_activity(
                activity_type="quiz",
                goal="クイズを行う",
                expected_input="回答",
                end_condition="クイズ終了",
                context={"plugin_id": "quiz_plugin"},
            )
        return None

    monkeypatch.setattr(runtime, "_route_plugin_user_input", route_switch_step)
    target_plan = ActivityPlan(
        decision=BehaviorDecision.SWITCH_ACTIVITY,
        activity_type="quiz",
        goal="クイズへ切り替える",
        required_capability="games.quiz",
        provider_plugin_id="quiz_plugin",
        operation=ActivityOperation.START,
        ongoing_input_decision=OngoingInputDecision.SWITCH_ACTIVITY,
        current_activity_type="shiritori",
        requested_new_activity="quiz",
    )
    context = BehaviorPlanningContext(
        user_text="しりとりはやめてクイズにしよう",
        source_event_id="switch-event",
        available_capabilities=frozenset({"games.shiritori", "games.quiz"}),
        activity_definitions=(current_definition,),
        active_activity_definition=current_definition,
        ongoing_activity_type="shiritori",
    )

    routed = await runtime._route_activity_switch(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": context.user_text},
        ),
        target_plan,
        context,
    )

    assert routed is None
    assert calls == ["stop", "start"]
    current = runtime.activity_manager.ongoing_activity
    assert current is not None
    assert current.activity_type == "quiz"


@pytest.mark.asyncio
async def test_natural_game_completion_completes_ongoing_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)

    await runtime.submit_user_text("しりとりしよう", source="console")
    await runtime.submit_user_text("みかん", source="console")

    assert games.snapshot()["session_status"] == "completed"
    assert runtime.activity_manager.ongoing_activity is None
    terminal = runtime.activity_manager.ongoing_activity_history[-1]
    assert terminal.status.value == "completed"
    assert len(terminal.turns) == 2

    await runtime.submit_user_text("しりとりってどんな遊び？", source="console")
    group = await runtime.run_once()

    assert group is not None
    assert runtime.last_behavior_evaluation is not None
    assert (
        runtime.last_behavior_evaluation.plan.decision == BehaviorDecision.CONVERSATION
    )
    assert runtime.activity_manager.ongoing_activity is None


@pytest.mark.asyncio
async def test_ongoing_creation_failure_rolls_back_game_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)

    def fail_start(**_: object) -> object:
        raise RuntimeError("test ongoing creation failure")

    monkeypatch.setattr(runtime.activity_manager, "start_ongoing_activity", fail_start)
    await runtime.submit_user_text("しりとりしよう", source="console")

    assert games.snapshot()["session_status"] == "canceled"
    assert runtime.activity_manager.ongoing_activity is None


@pytest.mark.asyncio
async def test_stale_plugin_session_id_cancels_both_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)

    await runtime.submit_user_text("しりとりしよう", source="console")
    runtime.activity_manager.update_ongoing_activity(
        context_updates={"plugin_session_id": "stale-session-id"}
    )
    await runtime.submit_user_text("みみず", source="console")

    assert games.snapshot()["session_status"] == "canceled"
    assert runtime.activity_manager.ongoing_activity is None


@pytest.mark.asyncio
async def test_runtime_stop_cancels_game_session_and_ongoing_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(_games_test_config())
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)

    await runtime.submit_user_text("しりとりしよう", source="console")
    engine = games._engine
    assert engine is not None
    runtime.stop()

    session = engine.get_current_session()
    assert session is not None
    assert session.status.value == "canceled"
    assert runtime.activity_manager.ongoing_activity is None
    assert (
        runtime.activity_manager.ongoing_activity_history[-1].status.value == "canceled"
    )


@pytest.mark.asyncio
async def test_unavailable_game_llm_rejects_before_session_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=True)
        ),
    )
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)
    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(config)
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)
    assert not runtime.plugin_manager.is_capability_available(
        PluginCapability.COMMAND_HANDLER.value, "games"
    )

    await runtime.submit_user_text("しりとりしたい", source="console")

    assert games.snapshot()["session_id"] is None
    assert runtime.activity_manager.ongoing_activity is None
    assert generator.game_call_count == 0


@pytest.mark.asyncio
async def test_capability_revoked_immediately_before_execution_is_not_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=True)
        ),
    )
    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(config)
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)
    runtime.plugin_manager.set_capability_availability(
        "games", PluginCapability.COMMAND_HANDLER.value, available=False
    )

    await runtime.submit_user_text("しりとりしよう", source="console")
    group = await runtime.run_once()

    assert games.snapshot()["session_id"] is None
    assert runtime.activity_manager.ongoing_activity is None
    assert group is not None
    assert generator.game_call_count == 0
    assert generator.conversation_call_count == 0


@pytest.mark.asyncio
async def test_provider_failure_revokes_execution_and_uses_safe_conversation_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=True)
        ),
    )
    monkeypatch.setattr(
        runtime_factory,
        "create_response_generator",
        lambda **_: FailingFactoryResponseGenerator(),
    )
    runtime = runtime_factory.create_runtime_coordinator(config)
    assert runtime.plugin_manager is not None
    games = runtime.plugin_manager.get_plugin("games")
    assert isinstance(games, GamesPlugin)

    await runtime.submit_user_text("しりとりしよう", source="console")
    group = await runtime.run_once()

    assert games.snapshot()["session_status"] == "canceled"
    assert runtime.activity_manager.ongoing_activity is None
    assert not runtime.plugin_manager.is_capability_available(
        PluginCapability.COMMAND_HANDLER.value, "games"
    )
    assert not runtime.plugin_manager.is_capability_available(
        PluginCapability.ACTIVITY_PROVIDER.value, "games"
    )
    assert group is not None
    assert (
        group.action_plans[0].text == "今はそれを一緒にできないんだ。別のお話をしよう。"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_conversation_calls"),
    [
        ("今日の最新ニュースを検索して", 0),
        ("私の声を聞いて", 0),
        ("一緒に星間航行シミュレーションを始めよう", 0),
        ("しりとりってどんな遊び？", 1),
    ],
)
async def test_unmatched_and_knowledge_requests_use_normal_conversation(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    expected_conversation_calls: int,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        plugins=replace(
            config.plugins, games=replace(config.plugins.games, enabled=False)
        ),
    )
    generator = FactoryShiritoriResponseGenerator()
    monkeypatch.setattr(
        runtime_factory, "create_response_generator", lambda **_: generator
    )
    runtime = runtime_factory.create_runtime_coordinator(config)

    await runtime.submit_user_text(text, source="console")
    group = await runtime.run_once()

    assert group is not None
    assert runtime.last_behavior_evaluation is not None
    assert (
        runtime.last_behavior_evaluation.plan.decision == BehaviorDecision.CONVERSATION
    )
    assert generator.game_call_count == 0
    assert generator.conversation_call_count == expected_conversation_calls
    assert all(
        "Plugin" not in plan.text and "Capability" not in plan.text
        for plan in group.action_plans
    )


def test_create_topic_classifier_returns_none_when_response_generator_is_dummy() -> (
    None
):
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
    )

    topic_classifier = create_topic_classifier(config)

    assert topic_classifier is None


def test_create_topic_classifier_uses_ollama_model() -> None:
    config = load_app_config()
    config = replace(
        config,
        topic_classifier=replace(config.topic_classifier, model="ollama_chat"),
    )

    topic_classifier = create_topic_classifier(config)

    assert isinstance(topic_classifier, LlmTopicClassifier)


def test_create_topic_classifier_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        topic_classifier=replace(config.topic_classifier, model="openai_chat"),
    )
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)

    topic_classifier = create_topic_classifier(config)

    assert topic_classifier is None


def test_create_topic_classifier_returns_llm_topic_classifier_when_response_generator_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        topic_classifier=replace(config.topic_classifier, model="openai_chat"),
    )
    monkeypatch.setenv(_openai_api_key_env(config), "test-api-key")

    topic_classifier = create_topic_classifier(config)

    assert isinstance(topic_classifier, LlmTopicClassifier)


# Helper functions for topic memory config manipulation
def _replace_topic_memory_enabled(config: AppConfig, enabled: bool) -> AppConfig:
    return replace(
        config,
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=enabled),
        ),
    )


def _replace_topic_memory_embedding_service(
    config: AppConfig, service: str
) -> AppConfig:
    model_key = config.memory.topic_memory.embedding_model
    return replace(
        config,
        models={
            **config.models,
            model_key: replace(config.models[model_key], service=service),
        },
    )


def _replace_topic_memory_database_type(
    config: AppConfig, database_type: str
) -> AppConfig:
    service_key = config.memory.topic_memory.database_service
    return replace(
        config,
        services={
            **config.services,
            service_key: replace(config.services[service_key], type=database_type),
        },
    )


def test_create_embedding_generator_returns_none_when_topic_memory_is_disabled() -> (
    None
):
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=False)

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_none_when_embedding_type_is_unsupported() -> (
    None
):
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_embedding_service(
        config, service="topic_memory_database"
    )

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_openai_embedding_generator_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.setenv(_openai_api_key_env(config), "test-api-key")

    embedding_generator = create_embedding_generator(config)

    assert isinstance(embedding_generator, OpenAIEmbeddingGenerator)


def test_create_topic_memory_store_returns_none_when_topic_memory_is_disabled() -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=False)

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_none_when_database_type_is_unsupported() -> (
    None
):
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_database_type(config, database_type="unsupported")

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_none_when_database_dsn_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.delenv(_database_dsn_env(config), raising=False)

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_postgres_topic_memory_store_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.setenv(
        _database_dsn_env(config),
        "postgresql://user:password@localhost:5432/ai_liver_test",
    )

    topic_memory_store = create_topic_memory_store(config)

    assert isinstance(topic_memory_store, PostgresTopicMemoryStore)


def _replace_topic_memory_summary_type(
    config: AppConfig, summary_type: str
) -> AppConfig:
    return replace(
        config,
        memory=replace(
            config.memory,
            topic_memory=replace(
                config.memory.topic_memory,
                summary=replace(
                    config.memory.topic_memory.summary,
                    type=summary_type,
                ),
            ),
        ),
    )


def test_create_memory_summary_generator_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap.runtime import create_memory_summary_generator

    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_summary_type(config, summary_type="llm")
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)

    memory_summary_generator = create_memory_summary_generator(config)

    assert memory_summary_generator is None


def test_create_memory_summary_generator_returns_llm_generator_when_response_generator_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.memory.llm_memory_summary_generator import (
        LlmMemorySummaryGenerator,
    )
    from app.bootstrap.runtime import create_memory_summary_generator

    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_summary_type(config, summary_type="llm")
    monkeypatch.setenv(_openai_api_key_env(config), "test-api-key")

    memory_summary_generator = create_memory_summary_generator(config)

    assert isinstance(memory_summary_generator, LlmMemorySummaryGenerator)
