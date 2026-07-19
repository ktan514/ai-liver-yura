from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from app.adapters.youtube.google_youtube_auth_service import (
    YOUTUBE_READONLY_SCOPE,
    GoogleYouTubeAuthConfig,
    GoogleYouTubeAuthService,
)
from app.plugins.youtube_streaming.domain import YouTubeAuthenticationStatus
from app.utils.trace import TraceLogger


def credentials(*, expired: bool = False) -> Credentials:
    value = Credentials(  # type: ignore[no-untyped-call]
        token="access-token-value",
        refresh_token="refresh-token-value",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret-value",
        scopes=[YOUTUBE_READONLY_SCOPE],
    )
    value.expiry = datetime.utcnow() + (
        timedelta(seconds=-60) if expired else timedelta(hours=1)
    )
    return value


def service() -> GoogleYouTubeAuthService:
    return GoogleYouTubeAuthService(
        GoogleYouTubeAuthConfig(
            "YOUTUBE_TEST_CLIENT_SECRET",
            "YOUTUBE_TEST_TOKEN",
            open_browser=False,
        )
    )


def configure_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, token_exists: bool = False
) -> tuple[Path, Path]:
    client = tmp_path / "client.json"
    client.write_text("{}", encoding="utf-8")
    token = tmp_path / "private" / "token.json"
    monkeypatch.setenv("YOUTUBE_TEST_CLIENT_SECRET", str(client))
    monkeypatch.setenv("YOUTUBE_TEST_TOKEN", str(token))
    if token_exists:
        token.parent.mkdir()
        token.write_text(
            credentials().to_json(),  # type: ignore[no-untyped-call]
            encoding="utf-8",
        )
    return client, token


def test_auth_reports_missing_env_and_client_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YOUTUBE_TEST_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("YOUTUBE_TEST_TOKEN", raising=False)
    state = service().get_state()
    assert state.status == YouTubeAuthenticationStatus.AUTHENTICATION_FAILED
    assert "Client Secret" in (state.failure_reason or "")

    monkeypatch.setenv("YOUTUBE_TEST_CLIENT_SECRET", "/missing/client.json")
    monkeypatch.setenv("YOUTUBE_TEST_TOKEN", "/missing/token.json")
    state = service().get_state()
    assert state.status == YouTubeAuthenticationStatus.AUTHENTICATION_FAILED
    assert "ファイル" in (state.failure_reason or "")


def test_auth_reports_token_missing_as_authentication_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure_paths(monkeypatch, tmp_path)
    assert (
        service().get_state().status
        == YouTubeAuthenticationStatus.AUTHENTICATION_REQUIRED
    )


def test_auth_loads_valid_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure_paths(monkeypatch, tmp_path, token_exists=True)
    auth = service()
    assert auth.get_state().status == YouTubeAuthenticationStatus.AUTHENTICATED
    assert auth.credentials().token == "access-token-value"


def test_auth_trace_never_contains_token_or_client_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure_paths(monkeypatch, tmp_path, token_exists=True)
    log_path = tmp_path / "auth.log"
    auth = GoogleYouTubeAuthService(
        GoogleYouTubeAuthConfig(
            "YOUTUBE_TEST_CLIENT_SECRET",
            "YOUTUBE_TEST_TOKEN",
            open_browser=False,
        ),
        trace_logger=TraceLogger(log_path),
    )
    assert auth.get_state().status == YouTubeAuthenticationStatus.AUTHENTICATED
    trace = log_path.read_text(encoding="utf-8")
    assert "access-token-value" not in trace
    assert "refresh-token-value" not in trace
    assert "client-secret-value" not in trace


def test_auth_refreshes_expired_token_and_saves_securely(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, token = configure_paths(monkeypatch, tmp_path)
    token.parent.mkdir()
    token.write_text(
        credentials(expired=True).to_json(),  # type: ignore[no-untyped-call]
        encoding="utf-8",
    )

    def refresh(value: Credentials, request: object) -> None:
        del request
        value.token = "refreshed-token"
        value.expiry = datetime.utcnow() + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", refresh)
    auth = service()
    assert auth.get_state().status == YouTubeAuthenticationStatus.AUTHENTICATED
    assert "refreshed-token" in token.read_text(encoding="utf-8")
    assert token.stat().st_mode & 0o777 == 0o600


def test_auth_refresh_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, token = configure_paths(monkeypatch, tmp_path)
    token.parent.mkdir()
    token.write_text(
        credentials(expired=True).to_json(),  # type: ignore[no-untyped-call]
        encoding="utf-8",
    )

    def fail(value: Credentials, request: object) -> None:
        del value, request
        raise RefreshError("refresh-token-value")  # type: ignore[no-untyped-call]

    monkeypatch.setattr(Credentials, "refresh", fail)
    state = service().get_state()
    assert state.status == YouTubeAuthenticationStatus.AUTHENTICATION_FAILED
    assert "refresh-token-value" not in (state.failure_reason or "")


def test_auth_corrupt_token_does_not_expose_internal_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, token = configure_paths(monkeypatch, tmp_path)
    token.parent.mkdir()
    token.write_text("not-json", encoding="utf-8")
    state = service().get_state()
    assert state.status == YouTubeAuthenticationStatus.AUTHENTICATION_FAILED
    assert (
        state.failure_reason
        == "保存済みYouTube OAuth Tokenが破損しています。再認証してください。"
    )


def test_initial_authentication_saves_token_without_logging_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, token = configure_paths(monkeypatch, tmp_path)

    class FakeFlow:
        def run_local_server(self, **kwargs: Any) -> Credentials:
            assert kwargs["open_browser"] is False
            return credentials()

    monkeypatch.setattr(
        "app.adapters.youtube.google_youtube_auth_service."
        "InstalledAppFlow.from_client_secrets_file",
        lambda *args, **kwargs: FakeFlow(),
    )
    state = service().authenticate()
    assert state.status == YouTubeAuthenticationStatus.AUTHENTICATED
    assert token.is_file()
    assert token.stat().st_mode & 0o777 == 0o600
    assert token.parent.stat().st_mode & 0o077 == 0
    assert "access-token-value" not in (state.failure_reason or "")
