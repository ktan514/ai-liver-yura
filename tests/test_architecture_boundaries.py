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


def test_youtube_streaming_plugin_has_no_framework_or_concrete_output_dependency() -> None:
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
