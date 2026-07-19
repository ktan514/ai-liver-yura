from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def python_files(relative: str) -> list[Path]:
    return sorted((ROOT / relative).rglob("*.py"))


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module)
    return values


def assert_no_imports(paths: list[Path], forbidden: tuple[str, ...]) -> None:
    violations = [
        f"{path.relative_to(ROOT)} -> {name}"
        for path in paths
        for name in imports(path)
        if name in forbidden or any(name.startswith(prefix) for prefix in forbidden)
    ]
    assert violations == []


def test_core_never_imports_plugin_concrete_packages() -> None:
    assert_no_imports(python_files("app/core"), ("app.plugins",))


def test_app_main_does_not_compose_obs_youtube_or_streaming_admin() -> None:
    assert_no_imports(
        [ROOT / "app/__main__.py"],
        (
            "app.plugins.youtube_streaming",
            "app.adapters.obs",
            "app.adapters.youtube",
            "app.admin_api",
        ),
    )


def test_shared_contracts_do_not_import_core_domain_plugins_or_adapters() -> None:
    assert_no_imports(
        python_files("app/shared"),
        (
            "app.core",
            "app.domain",
            "app.runtime",
            "app.plugins",
            "app.adapters",
            "app.admin_api",
        ),
    )


def test_plugins_do_not_import_core_internal_packages() -> None:
    assert_no_imports(python_files("app/plugins"), ("app.core",))


def test_domain_has_no_framework_adapter_or_plugin_dependency() -> None:
    assert_no_imports(
        python_files("app/domain"),
        (
            "app.adapters",
            "app.plugins",
            "app.admin_api",
            "fastapi",
            "PyQt6",
            "httpx",
            "psycopg",
        ),
    )


def test_application_usecases_do_not_import_concrete_adapters() -> None:
    assert_no_imports(python_files("app/usecases"), ("app.adapters",))


def test_admin_api_has_no_streaming_usecase_or_plugin_adapter_import() -> None:
    forbidden = (
        "app.usecases.comment_",
        "app.usecases.stream_",
        "app.plugins.youtube_streaming.application",
        "app.plugins.youtube_streaming.adapters",
    )
    assert_no_imports(python_files("app/admin_api"), forbidden)


def test_admin_api_depends_on_shared_contracts_not_core_internals() -> None:
    assert_no_imports(python_files("app/admin_api"), ("app.core",))


def test_youtube_streaming_plugin_has_no_framework_or_concrete_output_dependency() -> (
    None
):
    assert_no_imports(
        python_files("app/plugins/youtube_streaming"),
        (
            "app.admin_api",
            "streaming_admin",
            "app.runtime.runtime_coordinator",
            "app.adapters.tts",
            "app.adapters.live2d",
            "PyQt6",
            "fastapi",
        ),
    )


def test_youtube_streaming_plugin_owns_streaming_domain_and_application_logic() -> None:
    assert_no_imports(
        python_files("app/plugins/youtube_streaming"),
        ("app.core", "app.domain", "app.runtime", "app.usecases", "app.admin_api"),
    )


def test_streaming_activity_provider_does_not_import_core_domain_models() -> None:
    assert_no_imports(
        [ROOT / "app/plugins/youtube_streaming/public/activity_provider.py"],
        ("app.core", "app.domain", "app.runtime"),
    )


def test_youtube_streaming_core_gateway_depends_only_on_shared_contracts() -> None:
    assert_no_imports(
        [ROOT / "app/plugins/youtube_streaming/ports/core_activity.py"],
        (
            "app.core",
            "app.domain",
            "app.runtime",
            "app.ports",
            "app.usecases",
            "app.adapters",
            "app.admin_api",
        ),
    )


def test_youtube_streaming_demo_evidence_does_not_import_core_models() -> None:
    assert_no_imports(
        [ROOT / "app/plugins/youtube_streaming/adapters/manual_check_log.py"],
        ("app.core", "app.domain", "app.runtime", "app.ports", "app.usecases"),
    )


def test_runtime_coordinator_contains_no_streaming_specific_branch_or_import() -> None:
    path = ROOT / "app/runtime/runtime_coordinator.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden_fragments = ("stream", "youtube", "comment", "lifecycle")
    violations = sorted(
        {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and any(fragment in node.id.lower() for fragment in forbidden_fragments)
        }
    )
    assert violations == []


def test_runtime_services_do_not_import_concrete_prompt_builders() -> None:
    assert_no_imports(python_files("app/runtime"), ("app.adapters.prompt",))


def test_runtime_package_does_not_compose_concrete_adapters_or_plugins() -> None:
    assert_no_imports(python_files("app/runtime"), ("app.adapters", "app.plugins"))


def test_games_plugin_owns_game_implementation_without_core_legacy_imports() -> None:
    assert_no_imports(
        python_files("app/plugins/games"),
        (
            "app.domain.games",
            "app.runtime.game_engine",
            "app.runtime.game_input_classifier",
            "app.runtime.shiritori_game_service",
        ),
    )


def test_games_plugin_depends_only_on_its_own_modules_and_shared_contracts() -> None:
    assert_no_imports(
        python_files("app/plugins/games"),
        (
            "app.core",
            "app.domain",
            "app.runtime",
            "app.ports",
            "app.usecases",
            "app.adapters",
            "app.admin_api",
            "app.utils",
        ),
    )


def test_speech_synthesis_boundary_does_not_depend_on_emotion_state() -> None:
    assert_no_imports(
        [
            ROOT / "app/ports/speech_synthesizer.py",
            ROOT / "app/adapters/tts/voicevox_speech_synthesizer.py",
            ROOT / "app/usecases/execute_action_usecase.py",
        ],
        ("app.domain.emotions",),
    )


def test_voice_output_plugin_depends_only_on_shared_contracts() -> None:
    assert_no_imports(
        python_files("app/plugins/voice_output"),
        (
            "app.core",
            "app.domain",
            "app.runtime",
            "app.ports",
            "app.adapters",
            "app.utils",
        ),
    )


def test_llm_provider_plugin_depends_only_on_shared_contracts() -> None:
    assert_no_imports(
        python_files("app/plugins/llm_provider"),
        (
            "app.core",
            "app.domain",
            "app.runtime",
            "app.ports",
            "app.adapters",
            "app.utils",
        ),
    )


def test_relationship_memory_plugin_depends_only_on_shared_contracts() -> None:
    assert_no_imports(
        python_files("app/plugins/relationship_memory"),
        (
            "app.core",
            "app.domain",
            "app.runtime",
            "app.ports",
            "app.adapters",
            "app.utils",
        ),
    )


def test_agent_memory_plugin_depends_only_on_shared_contracts() -> None:
    assert_no_imports(
        python_files("app/plugins/agent_memory"),
        ("app.core", "app.domain", "app.runtime", "app.ports", "app.adapters"),
    )
