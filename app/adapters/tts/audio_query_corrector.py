from __future__ import annotations

from typing import Any, Protocol


class AudioQueryCorrector(Protocol):
    def correct(
        self,
        *,
        original_text: str,
        corrected_text: str,
        audio_query: dict[str, Any],
    ) -> dict[str, Any]: ...


class NoOpAudioQueryCorrector(AudioQueryCorrector):
    """初期実装用。VOICEVOXのAudioQueryを変更せず返す。"""

    def correct(
        self,
        *,
        original_text: str,
        corrected_text: str,
        audio_query: dict[str, Any],
    ) -> dict[str, Any]:
        return audio_query
