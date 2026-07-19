from __future__ import annotations


class ObsStatusMapper:
    @staticmethod
    def output_status(response: object) -> str:
        active = bool(getattr(response, "output_active", False))
        reconnecting = bool(getattr(response, "output_reconnecting", False))
        state = str(getattr(response, "output_state", "")).upper()
        if reconnecting or "RECONNECT" in state:
            return "reconnecting"
        if state in {"OBS_WEBSOCKET_OUTPUT_STARTING", "STARTING"}:
            return "starting"
        if state in {"OBS_WEBSOCKET_OUTPUT_STOPPING", "STOPPING"}:
            return "stopping"
        if "ERROR" in state or "FAIL" in state:
            return "failed"
        if active or state in {"OBS_WEBSOCKET_OUTPUT_STARTED", "ACTIVE", "STARTED"}:
            return "active"
        if (
            state in {"OBS_WEBSOCKET_OUTPUT_STOPPED", "IDLE", "STOPPED", ""}
            and not active
        ):
            return "idle"
        return "unknown"
