from __future__ import annotations

from datetime import datetime
from typing import Any

from streaming_admin.i18n.ja import status_label


def local_time(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "-"
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%Y/%m/%d %H:%M:%S")
        )
    except ValueError:
        return "-"


def failure_summary(snapshot: dict[str, Any]) -> str:
    failures = [str(value) for value in snapshot.get("failure_codes", [])]
    required = [
        str(item.get("failure_code") or item.get("summary_code"))
        for item in snapshot.get("checks", [])
        if item.get("required") and item.get("status") not in {"healthy", "degraded"}
    ]
    return "\n".join(dict.fromkeys(failures + required))


def display_status(value: object) -> str:
    return status_label(str(value or "unknown"))
