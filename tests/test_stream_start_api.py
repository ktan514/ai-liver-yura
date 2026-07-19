from __future__ import annotations

import time
from dataclasses import replace

from fastapi.testclient import TestClient

from app.adapters.streaming.fake_streaming_control import (
    FakeObsStreamingControlAdapter,
    FakeYouTubeStreamingControlAdapter,
)
from app.admin_api import create_admin_api
from app.bootstrap import compose_streaming, create_stream_preparation_runtime
from app.config.app_config import load_app_config
from app.plugins.youtube_streaming.application import StartStreamSessionUsecase
from app.plugins.youtube_streaming.domain import StreamSession, StreamSessionStatus


def ready_runtime(real_controls: bool) -> tuple[object, StreamSession]:
    runtime = create_stream_preparation_runtime(load_app_config())
    created = runtime.sessions.create(
        StreamSession(
            trace_id="prepare", selected_broadcast_id="broadcast", title="title"
        )
    )
    preparing = runtime.sessions.save(created.transition(StreamSessionStatus.PREPARING))
    ready = runtime.sessions.save(
        preparing.transition(StreamSessionStatus.READY, selected_stream_id="stream")
    )
    obs = FakeObsStreamingControlAdapter()
    youtube = FakeYouTubeStreamingControlAdapter()
    if real_controls:
        obs.adapter_type = "obs_websocket"
        youtube.adapter_type = "google"
    start = StartStreamSessionUsecase(
        sessions=runtime.sessions,
        obs=obs,
        youtube=youtube,
        poll_interval_seconds=0.001,
        step_timeout_seconds=0.01,
    )
    runtime = replace(runtime, start_usecase=start)
    return runtime, ready


def approval(ready: StreamSession) -> dict[str, object]:
    return {
        "command_id": "approval-command",
        "session_id": ready.session_id,
        "expected_state_version": ready.state_version,
        "approved_by": "operator",
    }


def test_approve_and_status_endpoints_complete_asynchronously() -> None:
    runtime, ready = ready_runtime(True)
    service = compose_streaming(runtime).admin_api
    with TestClient(create_admin_api(service, token="secret")) as client:
        headers = {"Authorization": "Bearer secret"}
        response = client.post(
            "/api/v1/streaming/session/start/approve",
            headers=headers,
            json=approval(ready),
        )
        assert response.status_code == 202
        for _ in range(20):
            status = client.get(
                "/api/v1/streaming/session/start/status", headers=headers
            )
            if status.status_code == 200:
                break
            time.sleep(0.005)
        assert status.json()["status"] == "live"
        assert status.json()["obs_output_status"] == "active"
        assert status.json()["youtube_stream_status"] == "active"
        assert status.json()["youtube_broadcast_status"] == "live"


def test_approve_endpoint_rejects_fake_adapter_and_version_mismatch() -> None:
    runtime, ready = ready_runtime(False)
    service = compose_streaming(runtime).admin_api
    client = TestClient(create_admin_api(service))
    response = client.post(
        "/api/v1/streaming/session/start/approve", json=approval(ready)
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stream.start.test_adapter"

    runtime, ready = ready_runtime(True)
    service = compose_streaming(runtime).admin_api
    client = TestClient(create_admin_api(service))
    payload = approval(ready)
    payload["expected_state_version"] = 999
    response = client.post("/api/v1/streaming/session/start/approve", json=payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stream.start.version_mismatch"
