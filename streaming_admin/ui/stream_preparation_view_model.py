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


def update_mode_label(value: object) -> str:
    return {
        "automatic": "自動",
        "manual": "手動",
        "event_driven": "イベント駆動",
    }.get(str(value), "不明")


def freshness_label(value: object) -> str:
    return {"fresh": "最新", "stale": "情報が古い", "unknown": "不明"}.get(
        str(value), "不明"
    )


def start_button_decision(
    snapshot: dict[str, Any], demo_mode: bool = False
) -> tuple[bool, str]:
    modes = snapshot.get("adapter_modes", {})
    if not isinstance(modes, dict):
        return False, "Adapter構成を確認できません。"
    supported = (
        modes.get("obs") == "obs_websocket"
        and modes.get("youtube") in {"fake", "google"}
    ) or (demo_mode and modes.get("youtube") == "fake")
    if snapshot.get("status") != "ready" or not snapshot.get("ready"):
        return False, "配信準備が完了していません。"
    if not supported:
        return False, "現在のAdapter構成では配信開始できません。"
    return True, ""
