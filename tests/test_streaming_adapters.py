from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.streaming import (
    FakeObsPreparationAdapter,
    FakeObsPreparationConfig,
    FakeYouTubePreparationAdapter,
    FakeYouTubePreparationConfig,
    VoiceVoxHealthAdapter,
    VoiceVoxHealthConfig,
    YamlRunOfShowRepository,
)
from app.domain.streaming import HealthStatus, YouTubeBroadcastSummary


@pytest.mark.asyncio
async def test_youtube_fake_controls_auth_bind_api_and_live_chat() -> None:
    adapter = FakeYouTubePreparationAdapter(
        FakeYouTubePreparationConfig(
            authenticated=False,
            api_available=False,
            broadcasts=(YouTubeBroadcastSummary("broadcast", "title"),),
            stream_bound=False,
            live_chat_enabled=False,
        )
    )
    assert await adapter.check_authentication() is False
    assert await adapter.health_check() is False
    assert await adapter.get_live_chat_id("broadcast") is None
    with pytest.raises(LookupError):
        await adapter.resolve_bound_stream("broadcast")


@pytest.mark.asyncio
async def test_obs_fake_exposes_only_inspection_state() -> None:
    adapter = FakeObsPreparationAdapter(
        FakeObsPreparationConfig(connected=True, output_status="active")
    )
    snapshot = await adapter.snapshot()
    assert snapshot.output_status == "active"
    assert not hasattr(adapter, "start_streaming")
    assert not hasattr(adapter, "stop_streaming")


def test_yaml_run_of_show_validates_required_fields(tmp_path: Path) -> None:
    valid = tmp_path / "valid.yaml"
    valid.write_text(
        "run_of_show_id: valid\ntitle: test\nversion: '1'\n"
        "planned_duration_seconds: 10\nsegments:\n  - title: main\n",
        encoding="utf-8",
    )
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        "run_of_show_id: invalid\ntitle: bad\nversion: '1'\n"
        "planned_duration_seconds: 0\nsegments: []\n",
        encoding="utf-8",
    )
    repository = YamlRunOfShowRepository(tmp_path)
    assert repository.validate("valid").segment_count == 1
    with pytest.raises(RuntimeError):
        repository.validate("invalid")
    with pytest.raises(RuntimeError):
        repository.validate("missing")


@pytest.mark.asyncio
async def test_voicevox_health_checks_version_speaker_and_player_without_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = VoiceVoxHealthAdapter(VoiceVoxHealthConfig("http://voicevox", 1, 89, "test-player"))
    calls: list[str] = []

    def get_json(path: str) -> object:
        calls.append(path)
        return "1.0" if path == "/version" else [{"styles": [{"id": 89}]}]

    monkeypatch.setattr(adapter, "_get_json", get_json)
    monkeypatch.setattr("shutil.which", lambda command: f"/bin/{command}")
    result = await adapter.check(required=True)
    assert result.status == HealthStatus.HEALTHY
    assert calls == ["/version", "/speakers"]


@pytest.mark.asyncio
async def test_voicevox_health_reports_missing_player(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = VoiceVoxHealthAdapter(VoiceVoxHealthConfig("http://voicevox", 1, 89, "missing"))
    monkeypatch.setattr(
        adapter,
        "_get_json",
        lambda path: "1.0" if path == "/version" else [{"styles": [{"id": 89}]}],
    )
    monkeypatch.setattr("shutil.which", lambda command: None)
    result = await adapter.check(required=True)
    assert result.status == HealthStatus.UNAVAILABLE
    assert "Command" in (result.failure_reason or "")
