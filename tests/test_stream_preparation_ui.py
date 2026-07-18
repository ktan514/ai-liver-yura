from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.admin_api import create_admin_api
from app.bootstrap import compose_streaming
from app.config.app_config import load_app_config
from app.runtime.runtime_factory import create_stream_preparation_runtime
from streaming_admin.client import CoreApiClient, CoreApiError
from streaming_admin.config import AdminClientConfig


def api_client(token: str = "secret") -> TestClient:
    runtime = create_stream_preparation_runtime(load_app_config())
    return TestClient(create_admin_api(compose_streaming(runtime).admin_api, token=token))


def test_admin_api_health_auth_and_secret_boundary() -> None:
    client = api_client()
    headers = {"Authorization": "Bearer secret"}
    assert client.get("/api/v1/health", headers=headers).status_code == 200
    payload = client.get("/api/v1/youtube/auth", headers=headers).json()
    assert payload["status"] == "authenticated"
    serialized = str(payload).lower()
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized
    assert "token_path" not in serialized
    assert client.get("/api/v1/health").status_code == 401
    health = client.get("/api/v1/health", headers=headers).json()
    assert health["config_path"].endswith("/config/config.yaml")
    assert health["adapter_modes"] == {"youtube": "fake", "obs": "obs_websocket"}
    assert set(health["obs_connection"]) == {"host", "port", "password_env_set"}
    assert isinstance(health["obs_connection"]["password_env_set"], bool)


def test_admin_api_options_and_prepare_are_dtos() -> None:
    client = api_client()
    headers = {"Authorization": "Bearer secret"}
    broadcasts = client.get("/api/v1/streaming/broadcasts", headers=headers).json()["items"]
    run_of_shows = client.get("/api/v1/streaming/run-of-shows", headers=headers).json()["items"]
    assert broadcasts[0]["display_label"]
    assert "bound_stream_id" not in broadcasts[0]
    response = client.post(
        "/api/v1/streaming/session/prepare",
        headers=headers,
        json={
            "command_id": "command-1",
            "session_id": None,
            "broadcast_id": broadcasts[0]["broadcast_id"],
            "run_of_show_id": run_of_shows[0]["run_of_show_id"],
            "expected_state_version": None,
        },
    )
    assert response.status_code == 200
    assert response.json()["session_id"]
    assert "selected_stream_id" not in response.json()


def test_core_api_client_reports_core_unavailable(monkeypatch: Any) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "request", fail)
    client = CoreApiClient(AdminClientConfig())
    try:
        client.health()
    except CoreApiError as error:
        assert error.code == "runtime.unavailable"
        assert error.retryable is True
    else:
        raise AssertionError("CoreApiError was not raised")


def test_structured_validation_error() -> None:
    client = api_client()
    response = client.post(
        "/api/v1/streaming/session/prepare",
        headers={"Authorization": "Bearer secret"},
        json={},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request.invalid"
    assert response.json()["error"]["trace_id"]


def test_admin_console_exposes_freshness_capabilities_diagnostics_and_settings() -> None:
    with api_client() as client:
        headers = {"Authorization": "Bearer secret"}
        console = client.get("/api/v1/admin/console", headers=headers)
        assert console.status_code == 200
        payload = console.json()
        assert {item["name"] for item in payload["services"]} == {"Core", "OBS", "YouTube"}
        assert all(item["update_mode"] for item in payload["services"])
        assert all(
            item["freshness"] in {"fresh", "stale", "unknown"} for item in payload["services"]
        )
        assert payload["adapter_capabilities"]["youtube"]["can_start_broadcast"] is True
        assert payload["operator_action"]["action_type"] == "none"
        assert len(payload["lifecycle_steps"]) == 8

        updated = client.patch(
            "/api/v1/admin/settings",
            headers=headers,
            json={"level": "DEBUG", "file_enabled": False, "ring_buffer_size": 7},
        )
        assert updated.status_code == 200
        assert updated.json()["settings"]["ring_buffer_size"] == 7
        diagnostics = client.get("/api/v1/admin/diagnostics", headers=headers).json()
        assert diagnostics["generated_at"]
        assert "recent_events" in diagnostics
