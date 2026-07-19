from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

from app.adapters.youtube.youtube_api_error_mapper import (
    YouTubeApiError,
    YouTubeApiErrorKind,
)
from app.plugins.youtube_streaming.domain import (
    YouTubeAuthenticationState,
    YouTubeAuthenticationStatus,
)
from app.utils.trace import TraceLogger

YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


class _TimeoutRequest:
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds
        self._request = Request()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["timeout"] = self._timeout_seconds
        return self._request(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class GoogleYouTubeAuthConfig:
    client_secret_path_env: str
    token_path_env: str
    request_timeout_seconds: float = 15.0
    open_browser: bool = True
    oauth_timeout_seconds: float = 300.0
    scopes: tuple[str, ...] = (YOUTUBE_READONLY_SCOPE,)


class GoogleYouTubeAuthService:
    def __init__(
        self,
        config: GoogleYouTubeAuthConfig,
        *,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self._config = config
        self._trace = trace_logger or TraceLogger()
        self._credentials: Credentials | None = None
        self._state = YouTubeAuthenticationState(
            YouTubeAuthenticationStatus.AUTHENTICATION_REQUIRED
        )
        self._lock = threading.RLock()

    @property
    def scopes(self) -> tuple[str, ...]:
        return self._config.scopes

    def get_state(self) -> YouTubeAuthenticationState:
        with self._lock:
            if self._credentials is not None and self._credentials.valid:
                return self._set_state(YouTubeAuthenticationStatus.AUTHENTICATED)
            try:
                self._validate_client_secret()
                token_path = self._token_path()
                if not token_path.is_file():
                    return self._set_state(
                        YouTubeAuthenticationStatus.AUTHENTICATION_REQUIRED
                    )
                credentials = self._load_credentials(token_path)
                if credentials.expired and credentials.refresh_token:
                    self._refresh(credentials)
                    self._save_credentials(credentials, token_path)
                if not credentials.valid:
                    return self._set_state(
                        YouTubeAuthenticationStatus.AUTHENTICATION_REQUIRED,
                        "保存済みTokenは利用できません。再認証してください。",
                    )
                if not credentials.has_scopes(  # type: ignore[no-untyped-call]
                    self._config.scopes
                ):
                    raise YouTubeApiError(
                        YouTubeApiErrorKind.PERMISSION,
                        "YouTube OAuthのread-only権限が不足しています。",
                    )
                self._credentials = credentials
                return self._set_state(YouTubeAuthenticationStatus.AUTHENTICATED)
            except YouTubeApiError as error:
                return self._set_state(
                    YouTubeAuthenticationStatus.AUTHENTICATION_FAILED,
                    error.safe_message,
                )

    def authenticate(self) -> YouTubeAuthenticationState:
        with self._lock:
            self._set_state(YouTubeAuthenticationStatus.AUTHENTICATION_IN_PROGRESS)
            try:
                client_secret_path = self._validate_client_secret()
                token_path = self._token_path()
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(client_secret_path), scopes=list(self._config.scopes)
                )
                credentials = flow.run_local_server(
                    port=0,
                    open_browser=self._config.open_browser,
                    authorization_prompt_message="YouTube OAuth認証を開始します。",
                    success_message="YouTube OAuth認証が完了しました。この画面を閉じてください。",
                    timeout_seconds=self._config.oauth_timeout_seconds,
                    access_type="offline",
                    prompt="consent",
                    include_granted_scopes="true",
                )
                if not isinstance(credentials, Credentials):
                    raise YouTubeApiError(
                        YouTubeApiErrorKind.AUTHENTICATION,
                        "YouTube OAuth認証結果が不正です。",
                    )
                if not credentials.has_scopes(  # type: ignore[no-untyped-call]
                    self._config.scopes
                ):
                    raise YouTubeApiError(
                        YouTubeApiErrorKind.PERMISSION,
                        "YouTube OAuthのread-only権限が付与されませんでした。",
                    )
                self._save_credentials(credentials, token_path)
                self._credentials = credentials
                return self._set_state(YouTubeAuthenticationStatus.AUTHENTICATED)
            except YouTubeApiError as error:
                return self._set_state(
                    YouTubeAuthenticationStatus.AUTHENTICATION_FAILED,
                    error.safe_message,
                )
            except Exception:
                return self._set_state(
                    YouTubeAuthenticationStatus.AUTHENTICATION_FAILED,
                    "YouTube OAuth認証に失敗しました。",
                )

    def credentials(self) -> Credentials:
        state = self.get_state()
        if state.status != YouTubeAuthenticationStatus.AUTHENTICATED:
            raise YouTubeApiError(
                YouTubeApiErrorKind.AUTHENTICATION,
                state.failure_reason or "YouTube OAuth認証が必要です。",
            )
        with self._lock:
            if self._credentials is None:
                raise YouTubeApiError(
                    YouTubeApiErrorKind.AUTHENTICATION,
                    "YouTube OAuth認証情報を取得できません。",
                )
            return self._credentials

    def _validate_client_secret(self) -> Path:
        value = os.getenv(self._config.client_secret_path_env)
        if not value:
            raise YouTubeApiError(
                YouTubeApiErrorKind.AUTHENTICATION,
                "YouTube OAuth Client Secretの環境変数が設定されていません。",
            )
        path = Path(value).expanduser()
        if not path.is_file():
            raise YouTubeApiError(
                YouTubeApiErrorKind.AUTHENTICATION,
                "YouTube OAuth Client Secretファイルが見つかりません。",
            )
        return path

    def _token_path(self) -> Path:
        value = os.getenv(self._config.token_path_env)
        if not value:
            raise YouTubeApiError(
                YouTubeApiErrorKind.AUTHENTICATION,
                "YouTube OAuth Token保存先の環境変数が設定されていません。",
            )
        return Path(value).expanduser()

    def _load_credentials(self, token_path: Path) -> Credentials:
        try:
            with self._file_lock(token_path):
                return cast(
                    Credentials,
                    Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                        str(token_path), scopes=list(self._config.scopes)
                    ),
                )
        except (
            ValueError,
            json.JSONDecodeError,
            OSError,
            KeyError,
            GoogleAuthError,
        ) as error:
            raise YouTubeApiError(
                YouTubeApiErrorKind.AUTHENTICATION,
                "保存済みYouTube OAuth Tokenが破損しています。再認証してください。",
            ) from error

    def _refresh(self, credentials: Credentials) -> None:
        try:
            credentials.refresh(  # type: ignore[no-untyped-call]
                _TimeoutRequest(self._config.request_timeout_seconds)
            )
        except (RefreshError, TransportError, OSError, TimeoutError) as error:
            raise YouTubeApiError(
                YouTubeApiErrorKind.AUTHENTICATION,
                "YouTube OAuth Tokenのrefreshに失敗しました。再認証してください。",
            ) from error

    def _save_credentials(self, credentials: Credentials, token_path: Path) -> None:
        parent = token_path.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary_path = token_path.with_name(
            f".{token_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        with self._file_lock(token_path):
            descriptor = os.open(
                temporary_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    output.write(credentials.to_json())  # type: ignore[no-untyped-call]
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary_path, token_path)
                token_path.chmod(0o600)
            finally:
                temporary_path.unlink(missing_ok=True)

    @contextmanager
    def _file_lock(self, token_path: Path) -> Iterator[None]:
        lock_path = token_path.with_name(f".{token_path.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except ImportError:
                pass
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except ImportError:
                pass
            os.close(descriptor)

    def _set_state(
        self,
        status: YouTubeAuthenticationStatus,
        failure_reason: str | None = None,
    ) -> YouTubeAuthenticationState:
        self._state = YouTubeAuthenticationState(status, failure_reason)
        self._trace.info(
            "youtube_auth:state_changed",
            status=status.value,
            failure_reason=failure_reason,
        )
        return self._state
