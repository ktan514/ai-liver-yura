from __future__ import annotations

from pathlib import Path

import yaml

from app.domain.streaming import RunOfShowSummary


class YamlRunOfShowRepository:
    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    def list_available(self) -> tuple[RunOfShowSummary, ...]:
        if not self._directory.exists():
            return ()
        items: list[RunOfShowSummary] = []
        for path in sorted(self._directory.glob("*.yaml")):
            try:
                items.append(self._read(path))
            except (RuntimeError, OSError, yaml.YAMLError):
                continue
        return tuple(items)

    def load(self, run_of_show_id: str) -> RunOfShowSummary:
        return self._read(self._path(run_of_show_id))

    def validate(self, run_of_show_id: str) -> RunOfShowSummary:
        return self.load(run_of_show_id)

    def _path(self, run_of_show_id: str) -> Path:
        if not run_of_show_id or Path(run_of_show_id).name != run_of_show_id:
            raise RuntimeError("RunOfShow IDが不正です。")
        return self._directory / f"{run_of_show_id}.yaml"

    @staticmethod
    def _read(path: Path) -> RunOfShowSummary:
        if not path.is_file():
            raise RuntimeError(f"RunOfShowが見つかりません: {path}")
        with path.open(encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        if not isinstance(raw, dict):
            raise RuntimeError("RunOfShowはobject形式で指定してください。")
        segments = raw.get("segments")
        duration = raw.get("planned_duration_seconds")
        if not isinstance(segments, list) or not segments:
            raise RuntimeError("RunOfShowのsegmentsは1件以上必要です。")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            raise RuntimeError("planned_duration_secondsは正の整数にしてください。")
        run_of_show_id = raw.get("run_of_show_id")
        title = raw.get("title")
        version = raw.get("version")
        if not all(isinstance(value, str) and value for value in (run_of_show_id, title, version)):
            raise RuntimeError("run_of_show_id, title, versionは必須です。")
        if not isinstance(run_of_show_id, str):
            raise RuntimeError("run_of_show_idは文字列です。")
        if not isinstance(title, str):
            raise RuntimeError("titleは文字列です。")
        if not isinstance(version, str):
            raise RuntimeError("versionは文字列です。")
        return RunOfShowSummary(
            run_of_show_id=run_of_show_id,
            title=title,
            planned_duration_seconds=duration,
            segment_count=len(segments),
            source_path=str(path),
            version=version,
        )
