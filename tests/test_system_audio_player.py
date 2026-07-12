from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.tts.system_audio_player import SystemAudioPlayer


@pytest.mark.asyncio
async def test_play_writes_temporary_wav_and_runs_command(monkeypatch) -> None:
    received_commands: list[list[str]] = []
    received_audio: list[bytes] = []
    monkeypatch.setattr(
        "app.adapters.tts.system_audio_player.shutil.which",
        lambda command: f"/usr/bin/{command}",
    )

    def fake_run(command, **kwargs) -> None:
        received_commands.append(command)
        received_audio.append(Path(command[1]).read_bytes())

    monkeypatch.setattr("app.adapters.tts.system_audio_player.subprocess.run", fake_run)
    player = SystemAudioPlayer(command="test-player")

    await player.play(b"RIFF-test-wav")

    assert received_commands[0][0] == "/usr/bin/test-player"
    assert received_audio == [b"RIFF-test-wav"]
    assert not Path(received_commands[0][1]).exists()


@pytest.mark.asyncio
async def test_play_raises_when_command_is_missing(monkeypatch) -> None:
    monkeypatch.setattr("app.adapters.tts.system_audio_player.shutil.which", lambda command: None)
    player = SystemAudioPlayer(command="missing-player")

    with pytest.raises(RuntimeError, match="見つかりません"):
        await player.play(b"RIFF-test-wav")
