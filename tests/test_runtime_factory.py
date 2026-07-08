from app.config.app_config import load_app_config
from app.runtime import RuntimeCoordinator, create_runtime_coordinator


def test_create_runtime_coordinator_returns_runtime_coordinator() -> None:
    config = load_app_config()

    runtime = create_runtime_coordinator(config)

    assert isinstance(runtime, RuntimeCoordinator)