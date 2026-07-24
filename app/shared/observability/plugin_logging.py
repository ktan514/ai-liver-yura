from __future__ import annotations

import logging


class PluginLogger:
    """Core TraceContextへ依存しないPlugin向け構造化logging facade。"""

    def __init__(self, name: str = "yura.plugin") -> None:
        self._logger = logging.getLogger(name)

    def debug(self, label: str, **values: object) -> None:
        self._write(logging.DEBUG, label, values)

    def info(self, label: str, **values: object) -> None:
        self._write(logging.INFO, label, values)

    def warning(self, label: str, **values: object) -> None:
        self._write(logging.WARNING, label, values)

    def error(self, label: str, **values: object) -> None:
        self._write(logging.ERROR, label, values)

    def _write(self, level: int, label: str, values: dict[str, object]) -> None:
        details = " ".join(f"{key}={value!r}" for key, value in sorted(values.items()))
        self._logger.log(level, "%s%s", label, f" {details}" if details else "")
