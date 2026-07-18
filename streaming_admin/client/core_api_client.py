from __future__ import annotations

from typing import Any

import httpx

from streaming_admin.config import AdminClientConfig


class CoreApiError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class CoreApiClient:
    def __init__(self, config: AdminClientConfig) -> None:
        self.config = config
        self.manual_check_enabled = False

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.token}"} if self.config.token else {}

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        try:
            response = httpx.request(
                method,
                f"{self.config.base_url}{path}",
                headers=self.headers,
                json=json,
                timeout=self.config.timeout_seconds,
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise CoreApiError("runtime.unavailable", "Coreへ接続できません。", True) from error
        if response.is_error:
            detail = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise CoreApiError(
                str(detail.get("code", "runtime.unavailable")),
                str(detail.get("message", "Core API request failed")),
                bool(detail.get("retryable", False)),
            )
        return payload

    def health(self) -> dict[str, Any]:
        value = dict(self._request("GET", "/api/v1/health"))
        manual = value.get("manual_check_log")
        self.manual_check_enabled = isinstance(manual, dict) and bool(manual.get("enabled"))
        return value

    def manual_check_ui_event(self, event: str, details: dict[str, Any] | None = None) -> None:
        self._request(
            "POST",
            "/api/v1/manual-check/ui-events",
            {"event": event, "details": details or {}},
        )

    def console_snapshot(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/admin/console"))

    def diagnostics(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/admin/diagnostics"))

    def save_diagnostics(self) -> dict[str, Any]:
        return dict(self._request("POST", "/api/v1/admin/diagnostics/save"))

    def settings(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/admin/settings"))

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("PATCH", "/api/v1/admin/settings", payload))

    def auth_status(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/youtube/auth"))

    def start_auth(self, command_id: str) -> dict[str, Any]:
        return dict(self._request("POST", "/api/v1/youtube/auth/start", {"command_id": command_id}))

    def broadcasts(self, refresh: bool = False) -> list[dict[str, Any]]:
        method = "POST" if refresh else "GET"
        path = "/api/v1/streaming/broadcasts/refresh" if refresh else "/api/v1/streaming/broadcasts"
        return list(self._request(method, path)["items"])

    def run_of_shows(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/api/v1/streaming/run-of-shows")["items"])

    def capabilities(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/api/v1/capabilities")["items"])

    def session(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/streaming/session"))

    def prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", "/api/v1/streaming/session/prepare", payload))

    def refresh_obs(self) -> dict[str, Any]:
        return dict(self._request("POST", "/api/v1/obs/refresh"))

    def approve_start(
        self, command_id: str, session_id: str, state_version: int, approved_by: str
    ) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/api/v1/streaming/session/start/approve",
                {
                    "command_id": command_id,
                    "session_id": session_id,
                    "expected_state_version": state_version,
                    "approved_by": approved_by,
                },
            )
        )

    def start_status(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/streaming/session/start/status"))

    def opening_status(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/streaming/session/opening"))

    def retry_opening(
        self, command_id: str, session_id: str, expected_activity_version: int
    ) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/api/v1/streaming/session/opening/retry",
                {
                    "command_id": command_id,
                    "session_id": session_id,
                    "expected_activity_version": expected_activity_version,
                },
            )
        )

    def main_segment_status(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/streaming/session/main-segment"))

    def retry_main_segment(
        self, command_id: str, session_id: str, activity_id: str, version: int
    ) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/api/v1/streaming/session/main-segment/retry",
                {
                    "command_id": command_id,
                    "session_id": session_id,
                    "activity_id": activity_id,
                    "expected_activity_version": version,
                },
            )
        )

    def approve_end(self, command_id: str, session_id: str, version: int) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/api/v1/streaming/session/end/approve",
                {
                    "command_id": command_id,
                    "session_id": session_id,
                    "expected_state_version": version,
                    "approved_by": self.config.operator,
                },
            )
        )

    def emergency_stop(
        self, command_id: str, session_id: str, version: int, reason_code: str
    ) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/api/v1/streaming/session/emergency-stop",
                {
                    "command_id": command_id,
                    "session_id": session_id,
                    "expected_state_version": version,
                    "requested_by": self.config.operator,
                    "reason_code": reason_code,
                },
            )
        )

    def end_status(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/streaming/session/end/status"))

    def lifecycle(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/streaming/session/lifecycle"))

    def comments_status(self, refresh: bool = False) -> dict[str, Any]:
        return dict(
            self._request(
                "POST" if refresh else "GET",
                "/api/v1/streaming/session/comments/refresh-status"
                if refresh
                else "/api/v1/streaming/session/comments/status",
            )
        )

    def moderation_status(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/streaming/session/comments/moderation/status"))

    def ranking_status(self) -> dict[str, Any]:
        status = dict(self._request("GET", "/api/v1/streaming/session/comments/ranking/status"))
        status["top"] = self._request("GET", "/api/v1/streaming/session/comments/ranking/top").get(
            "items", []
        )
        status["current_selection"] = self._request(
            "GET", "/api/v1/streaming/session/comments/selection/current"
        ).get("selection")
        return status

    def comment_response_status(self) -> dict[str, Any]:
        return dict(self._request("GET", "/api/v1/streaming/session/comments/response/status"))

    def retry_comment_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(
            self._request("POST", "/api/v1/streaming/session/comments/response/retry", payload)
        )

    def enqueue_demo_comment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", "/api/v1/demo/live-chat/messages", payload))
