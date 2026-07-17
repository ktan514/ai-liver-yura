from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ManualCheckLogReader:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.path: Path | None = None
        self.offset = 0
        self._pending = b""
        self._line_number = 0

    def set_path(self, value: str | Path | None) -> None:
        path = self._resolve(value) if value else self.latest_path()
        if path != self.path:
            self.path = path
            self.offset = 0
            self._pending = b""
            self._line_number = 0

    def latest_path(self) -> Path | None:
        directory = self.root / "logs" / "manual_checks"
        files = tuple(directory.glob("streaming_demo_*.jsonl"))
        return max(files, key=lambda item: item.stat().st_mtime_ns) if files else None

    def discover_newer(self) -> bool:
        latest = self.latest_path()
        if latest is None:
            return False
        if (
            self.path is None
            or not self.path.exists()
            or latest != self.path
            and latest.stat().st_mtime_ns >= self.path.stat().st_mtime_ns
        ):
            self.set_path(latest)
            return True
        return False

    def reload(self) -> list[dict[str, Any]]:
        current = self.path
        self.path = None
        self.set_path(current or self.latest_path())
        return self.read_new()

    def skip_existing(self) -> None:
        if self.path is not None and self.path.exists():
            self.offset = self.path.stat().st_size
            self._pending = b""

    def read_new(self) -> list[dict[str, Any]]:
        if self.path is None:
            self.set_path(None)
        if self.path is None or not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self.offset:
            self.offset = 0
            self._pending = b""
            self._line_number = 0
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            chunk = stream.read()
            self.offset = stream.tell()
        data = self._pending + chunk
        complete, separator, pending = data.rpartition(b"\n")
        if not separator:
            self._pending = data
            return []
        self._pending = pending
        values: list[dict[str, Any]] = []
        for raw in complete.splitlines():
            self._line_number += 1
            if not raw.strip():
                continue
            try:
                value = json.loads(raw.decode("utf-8"))
                if isinstance(value, dict):
                    values.append(value)
                else:
                    raise ValueError("JSON object required")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                values.append(
                    {
                        "source": "ui",
                        "category": "error",
                        "event": "parse_error",
                        "status": "failed",
                        "reason": (
                            f"JSONL解析エラー: line {self._line_number}: {type(error).__name__}"
                        ),
                        "details": {},
                    }
                )
        return values

    def _resolve(self, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path
