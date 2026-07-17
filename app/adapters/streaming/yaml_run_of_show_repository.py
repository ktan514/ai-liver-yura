from __future__ import annotations

from pathlib import Path

import yaml

from app.domain.streaming import RunOfShowSegment, RunOfShowSummary


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

    def get_opening_segment(self, run_of_show_id: str) -> RunOfShowSegment | None:
        segments = self._get_segments(run_of_show_id, "opening", single=True)
        return segments[0] if segments else None

    def get_first_main_segment(self, run_of_show_id: str) -> RunOfShowSegment | None:
        segments = self._get_segments(run_of_show_id, "main", single=False)
        return segments[0] if segments else None

    def get_closing_segment(self, run_of_show_id: str) -> RunOfShowSegment | None:
        segments = self._get_segments(run_of_show_id, "closing", single=True)
        return segments[0] if segments else None

    def _get_segments(
        self, run_of_show_id: str, segment_type: str, *, single: bool
    ) -> tuple[RunOfShowSegment, ...]:
        path = self._path(run_of_show_id)
        if not path.is_file():
            raise RuntimeError("opening.run_of_show.not_found")
        with path.open(encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        if not isinstance(raw, dict) or not isinstance(raw.get("segments"), list):
            raise RuntimeError("opening.run_of_show.invalid")
        matches = [
            (index, item)
            for index, item in enumerate(raw["segments"])
            if isinstance(item, dict) and item.get("segment_type") == segment_type
        ]
        if not matches:
            return ()
        if single and len(matches) != 1:
            raise RuntimeError("opening.segment.ambiguous")
        parsed: list[RunOfShowSegment] = []
        for index, item in matches:
            parsed.append(self._parse_segment(item, index))
        return tuple(sorted(parsed, key=lambda item: item.order))

    @staticmethod
    def _parse_segment(item: dict[object, object], index: int) -> RunOfShowSegment:
        required_fields = (
            "segment_id",
            "segment_type",
            "title",
            "duration_seconds",
            "required",
            "script_mode",
            "prompt_template_id",
        )
        if any(field not in item for field in required_fields):
            raise RuntimeError("opening.segment.invalid")
        if (
            not all(
                isinstance(item[field], str) and item[field]
                for field in (
                    "segment_id",
                    "segment_type",
                    "title",
                    "script_mode",
                    "prompt_template_id",
                )
            )
            or not isinstance(item["duration_seconds"], int)
            or isinstance(item["duration_seconds"], bool)
            or item["duration_seconds"] <= 0
            or not isinstance(item["required"], bool)
        ):
            raise RuntimeError("opening.segment.invalid")
        order = item.get("order", index)
        if not isinstance(order, int) or isinstance(order, bool):
            raise RuntimeError("opening.segment.invalid")
        intent = item.get("intent")
        topic = item.get("topic")
        if intent is not None and not isinstance(intent, str):
            raise RuntimeError("opening.segment.invalid")
        if topic is not None and not isinstance(topic, str):
            raise RuntimeError("opening.segment.invalid")
        return RunOfShowSegment(
            segment_id=str(item["segment_id"]),
            segment_type=str(item["segment_type"]),
            title=str(item["title"]),
            duration_seconds=item["duration_seconds"],
            required=item["required"],
            script_mode=str(item["script_mode"]),
            prompt_template_id=str(item["prompt_template_id"]),
            order=order,
            intent=intent,
            topic=topic,
        )

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
