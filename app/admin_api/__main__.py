from __future__ import annotations

import logging
import os

import uvicorn

from app.admin_api import create_admin_api
from app.bootstrap import compose_streaming, create_stream_preparation_runtime
from app.config.app_config import load_app_config


def main() -> None:
    host = os.getenv("AI_LIVER_ADMIN_API_HOST", "127.0.0.1")
    token = os.getenv("AI_LIVER_ADMIN_API_TOKEN")
    if host not in {"127.0.0.1", "localhost", "::1"} and not token:
        raise RuntimeError(
            "localhost以外へbindする場合はAI_LIVER_ADMIN_API_TOKENが必要です。"
        )
    port = int(os.getenv("AI_LIVER_ADMIN_API_PORT", "8765"))
    runtime = create_stream_preparation_runtime(load_app_config())
    obs_settings = runtime.config.services["obs"]
    logging.getLogger("uvicorn.error").info(
        "Streaming config loaded: config_path=%s youtube_adapter=%s obs_adapter=%s "
        "obs_host=%s obs_port=%s obs_password_env_set=%s",
        runtime.config.config_path,
        runtime.usecase.youtube_adapter_type,
        runtime.usecase.obs_adapter_type,
        obs_settings.host,
        obs_settings.port,
        bool(obs_settings.password_env and os.getenv(obs_settings.password_env)),
    )
    composition = compose_streaming(runtime)
    uvicorn.run(create_admin_api(composition.admin_api, token), host=host, port=port)


if __name__ == "__main__":
    main()
