from __future__ import annotations

import os

import uvicorn

from app.admin_api import AdminApiService, create_admin_api
from app.config.app_config import load_app_config
from app.runtime.runtime_factory import create_stream_preparation_runtime


def main() -> None:
    host = os.getenv("AI_LIVER_ADMIN_API_HOST", "127.0.0.1")
    token = os.getenv("AI_LIVER_ADMIN_API_TOKEN")
    if host not in {"127.0.0.1", "localhost", "::1"} and not token:
        raise RuntimeError("localhost以外へbindする場合はAI_LIVER_ADMIN_API_TOKENが必要です。")
    port = int(os.getenv("AI_LIVER_ADMIN_API_PORT", "8765"))
    runtime = create_stream_preparation_runtime(load_app_config())
    uvicorn.run(create_admin_api(AdminApiService(runtime), token), host=host, port=port)


if __name__ == "__main__":
    main()
