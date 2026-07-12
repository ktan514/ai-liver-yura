from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app.ports.audio_player import AudioPlayer


class SystemAudioPlayer(AudioPlayer):
    """OS標準コマンドを使ってWAV音声を再生する。"""

    def __init__(self, command: str | None = None) -> None:
        self._command = command or self._default_command()

    async def play(self, audio_data: bytes) -> None:
        if not audio_data:
            raise ValueError("再生する音声データが空です。")
        await asyncio.to_thread(self._play_sync, audio_data)

    def _play_sync(self, audio_data: bytes) -> None:
        executable = shutil.which(self._command)
        if executable is None:
            raise RuntimeError(f"音声再生コマンドが見つかりません: {self._command}")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
                audio_file.write(audio_data)
                temporary_path = Path(audio_file.name)
            subprocess.run(
                [executable, str(temporary_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"音声再生に失敗しました: {message}") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _default_command() -> str:
        if sys.platform == "darwin":
            return "afplay"
        if sys.platform.startswith("linux"):
            return "aplay"
        raise RuntimeError("このOSでは音声再生コマンドを明示的に設定してください。")
