from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httplib2  # type: ignore[import-untyped]
from google_auth_httplib2 import AuthorizedHttp  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from app.adapters.youtube.google_youtube_auth_service import GoogleYouTubeAuthService


@dataclass(frozen=True, slots=True)
class GoogleYouTubeClientConfig:
    request_timeout_seconds: float = 15.0


class GoogleYouTubeClientFactory:
    """呼出しごとに独立した同期Clientを作り、httplib2を共有しない。"""

    def __init__(
        self,
        auth_service: GoogleYouTubeAuthService,
        config: GoogleYouTubeClientConfig,
    ) -> None:
        self._auth_service = auth_service
        self._config = config

    def create(self) -> Any:
        credentials = self._auth_service.credentials()
        transport = httplib2.Http(timeout=self._config.request_timeout_seconds)
        authorized_http = AuthorizedHttp(credentials, http=transport)
        return build(
            "youtube",
            "v3",
            http=authorized_http,
            cache_discovery=False,
            static_discovery=True,
        )
