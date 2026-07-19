from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import httpx
from PyQt6.QtCore import QObject, pyqtSignal

from streaming_admin.client import CoreApiClient, CoreApiError

logger = logging.getLogger(__name__)


class StreamPreparationController(QObject):
    loaded = pyqtSignal(object)
    auth_changed = pyqtSignal(object)
    broadcasts_changed = pyqtSignal(object)
    run_of_shows_changed = pyqtSignal(object)
    session_changed = pyqtSignal(object)
    obs_changed = pyqtSignal(object)
    start_changed = pyqtSignal(object)
    opening_changed = pyqtSignal(object)
    main_segment_changed = pyqtSignal(object)
    end_changed = pyqtSignal(object)
    lifecycle_changed = pyqtSignal(object)
    comments_changed = pyqtSignal(object)
    moderation_changed = pyqtSignal(object)
    ranking_changed = pyqtSignal(object)
    comment_response_changed = pyqtSignal(object)
    busy_changed = pyqtSignal(str, bool)
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)
    console_changed = pyqtSignal(object)
    diagnostics_changed = pyqtSignal(object)
    settings_changed = pyqtSignal(object)

    def __init__(self, client: CoreApiClient) -> None:
        super().__init__()
        self.client = client
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="admin-api")
        self._busy: set[str] = set()
        self._state_lock = threading.RLock()
        self._shutdown_callbacks: list[Callable[[], None]] = []
        self._closing = False
        self._closed = False
        self._core_connected = False
        self._sse_connected = False
        self._bootstrap_pending = False

    def load(self) -> None:
        if self._is_stopping():
            return
        if "load" in self._busy:
            self._bootstrap_pending = True
            return

        def action() -> dict[str, Any]:
            def optional(name: str) -> dict[str, Any] | None:
                callback = getattr(self.client, name, None)
                if not callable(callback):
                    return None
                try:
                    value = callback()
                except CoreApiError as error:
                    if error.code.endswith("not_found"):
                        return None
                    raise
                return value if isinstance(value, dict) else None

            health = self.client.health()
            return {
                "health": health,
                "auth": self.client.auth_status(),
                "broadcasts": self.client.broadcasts(),
                "run_of_shows": self.client.run_of_shows(),
                "capabilities": self.client.capabilities(),
                "session": optional("session"),
                "comments": optional("comments_status"),
                "moderation": optional("moderation_status"),
                "ranking": optional("ranking_status"),
                "comment_response": optional("comment_response_status"),
                "console": optional("console_snapshot"),
            }

        self._submit("load", action, self._loaded)

    def authenticate(self) -> None:
        self._submit(
            "auth", lambda: self.client.start_auth(str(uuid4())), lambda _: None
        )

    def refresh_broadcasts(self) -> None:
        self._manual_event("reload_slots_clicked")

        def refresh() -> dict[str, object]:
            return {
                "broadcasts": self.client.broadcasts(True),
                "run_of_shows": self.client.run_of_shows(),
            }

        self._submit("broadcasts", refresh, self._broadcasts_refreshed)

    def core_connection_changed(self, connected: bool) -> None:
        """Track SSE separately and use it only to trigger a REST bootstrap."""
        if self._is_stopping():
            return
        was_connected = self._sse_connected
        self._sse_connected = connected
        if connected and not was_connected:
            self.refresh_after_core_connected()

    def refresh_after_core_connected(self) -> None:
        """Reload every bootstrap resource needed by the current screen."""
        self.load()

    def refresh_obs(self) -> None:
        self._submit("obs", self.client.refresh_obs, self.obs_changed.emit)

    def refresh_console(self) -> None:
        callback = getattr(self.client, "console_snapshot", None)
        if callable(callback):
            self._submit("console", callback, self.console_changed.emit)

    def refresh_youtube(self) -> None:
        def action() -> dict[str, object]:
            return {
                "auth": self.client.auth_status(),
                "broadcasts": self.client.broadcasts(True),
            }

        self._submit("youtube", action, self._youtube_refreshed)

    def reconnect_obs(self) -> None:
        self.error_occurred.emit(
            "OBS再接続capabilityは現在のCoreで提供されていません。"
        )

    def load_diagnostics(self) -> None:
        callback = getattr(self.client, "diagnostics", None)
        if callable(callback):
            self._submit("diagnostics", callback, self.diagnostics_changed.emit)

    def save_diagnostics(self) -> None:
        callback = getattr(self.client, "save_diagnostics", None)
        if callable(callback):
            self._submit("diagnostics-save", callback, self.diagnostics_changed.emit)

    def update_settings(self, payload: dict[str, Any]) -> None:
        callback = getattr(self.client, "update_settings", None)
        if callable(callback):
            self._submit(
                "settings", lambda: callback(payload), self.settings_changed.emit
            )

    def prepare(self, broadcast_id: str, run_of_show_id: str) -> None:
        self._manual_event("prepare_clicked")
        payload = {
            "command_id": str(uuid4()),
            "session_id": None,
            "broadcast_id": broadcast_id,
            "run_of_show_id": run_of_show_id,
            "expected_state_version": None,
        }
        self._submit(
            "prepare", lambda: self.client.prepare(payload), self.session_changed.emit
        )

    def approve_start(self, session_id: str, state_version: int) -> None:
        self._manual_event("start_clicked")
        self._submit(
            "start",
            lambda: self.client.approve_start(
                str(uuid4()), session_id, state_version, self.client.config.operator
            ),
            lambda _: None,
        )

    def retry_opening(self, session_id: str, version: int) -> None:
        self._submit(
            "opening-retry",
            lambda: self.client.retry_opening(str(uuid4()), session_id, version),
            self.opening_changed.emit,
        )

    def retry_main_segment(
        self, session_id: str, activity_id: str, version: int
    ) -> None:
        self._submit(
            "main-segment-retry",
            lambda: self.client.retry_main_segment(
                str(uuid4()), session_id, activity_id, version
            ),
            self.main_segment_changed.emit,
        )

    def approve_end(self, session_id: str, version: int) -> None:
        self._manual_event("normal_end_clicked")
        self._submit(
            "end",
            lambda: self.client.approve_end(str(uuid4()), session_id, version),
            self.end_changed.emit,
        )

    def emergency_stop(self, session_id: str, version: int, reason_code: str) -> None:
        self._manual_event("emergency_stop_clicked")
        self._submit(
            "emergency-stop",
            lambda: self.client.emergency_stop(
                str(uuid4()), session_id, version, reason_code
            ),
            self.end_changed.emit,
        )

    def retry_comment_response(
        self, session_id: str, activity_id: str, selection_id: str, version: int
    ) -> None:
        payload = {
            "command_id": str(uuid4()),
            "session_id": session_id,
            "activity_id": activity_id,
            "selection_id": selection_id,
            "expected_activity_version": version,
        }
        self._submit(
            "comment-response-retry",
            lambda: self.client.retry_comment_response(payload),
            self.comment_response_changed.emit,
        )

    def enqueue_demo_comment(self, payload: dict[str, Any]) -> None:
        payload = {
            **payload,
            "test_case_id": str(payload.get("test_case_id") or uuid4()),
        }
        self._manual_event(
            "demo_comment_submitted",
            {
                "preset": str(payload.get("preset") or "custom"),
                "text_length": len(str(payload.get("text") or "")),
                "is_paid": bool(payload.get("is_paid")),
            },
        )
        self._submit(
            "demo-comment",
            lambda: self.client.enqueue_demo_comment(payload),
            lambda _: self._submit(
                "comments-status",
                self.client.comments_status,
                self.comments_changed.emit,
            ),
        )

    def handle_event(self, event: object) -> None:
        if self._is_stopping():
            return
        event_type = getattr(event, "event_type", "")
        data = getattr(event, "data", {})
        if event_type.startswith("youtube.auth."):
            self._submit("auth-status", self.client.auth_status, self.auth_changed.emit)
        elif event_type == "youtube.broadcasts.updated":
            self.broadcasts_changed.emit(data.get("items", []))
        elif event_type.startswith("stream_preparation.") and isinstance(data, dict):
            self.session_changed.emit(data)
        elif event_type == "obs.status.updated" and isinstance(data, dict):
            self.obs_changed.emit(data)
        elif event_type.startswith("stream_start."):
            self._submit(
                "start-status", self.client.start_status, self.start_changed.emit
            )
        elif event_type.startswith("stream_opening."):
            self._submit(
                "opening-status", self.client.opening_status, self.opening_changed.emit
            )
        elif event_type.startswith("stream_main_segment."):
            self._submit(
                "main-segment-status",
                self.client.main_segment_status,
                self.main_segment_changed.emit,
            )
        elif (
            event_type.startswith("stream_end.")
            or event_type.startswith("stream_closing.")
            or event_type.startswith("stream_emergency_stop.")
        ):
            self._submit("end-status", self.client.end_status, self.end_changed.emit)
        if event_type.startswith(
            (
                "stream_lifecycle.",
                "stream_start.",
                "stream_opening.",
                "stream_main_segment.",
                "stream_end.",
                "stream_emergency_stop.",
            )
        ):
            self._submit(
                "lifecycle", self.client.lifecycle, self.lifecycle_changed.emit
            )
            self._submit(
                "session-status", self.client.session, self.session_changed.emit
            )
        if event_type != "runtime.connected":
            self.refresh_console()
        if event_type.startswith("stream_comments."):
            self._submit(
                "comments-status",
                self.client.comments_status,
                self.comments_changed.emit,
            )
        if (
            event_type.startswith("stream_comments.moderation_")
            or event_type == "stream_comments.candidate_created"
        ):
            self._submit(
                "moderation-status",
                self.client.moderation_status,
                self.moderation_changed.emit,
            )
        if event_type.startswith("stream_comments.ranking_") or event_type.startswith(
            "stream_comments.target_"
        ):
            self._submit(
                "ranking-status", self.client.ranking_status, self.ranking_changed.emit
            )
        if event_type.startswith("stream_comments.response_") or event_type.startswith(
            "stream_comments.reservation_"
        ):
            self._submit(
                "comment-response-status",
                self.client.comment_response_status,
                self.comment_response_changed.emit,
            )

    def _loaded(self, value: object) -> None:
        if self._is_stopping():
            return
        self._manual_event("streaming_admin_connected")
        self.loaded.emit(value)
        if isinstance(value, dict):
            for key, signal in (
                ("session", self.session_changed),
                ("comments", self.comments_changed),
                ("moderation", self.moderation_changed),
                ("ranking", self.ranking_changed),
                ("comment_response", self.comment_response_changed),
            ):
                item = value.get(key)
                if isinstance(item, dict):
                    signal.emit(item)
            console = value.get("console")
            if isinstance(console, dict):
                self.console_changed.emit(console)

    def _broadcasts_refreshed(self, value: object) -> None:
        if not isinstance(value, dict):
            return
        self.broadcasts_changed.emit(value.get("broadcasts", []))
        self.run_of_shows_changed.emit(value.get("run_of_shows", []))

    def _youtube_refreshed(self, value: object) -> None:
        if not isinstance(value, dict):
            return
        self.auth_changed.emit(value.get("auth", {}))
        self.broadcasts_changed.emit(value.get("broadcasts", []))
        self.refresh_console()

    def _submit(
        self,
        operation: str,
        action: Callable[[], object],
        done: Callable[[object], None],
    ) -> None:
        with self._state_lock:
            if self._closing or self._closed or operation in self._busy:
                return
            self._busy.add(operation)
        self.busy_changed.emit(operation, True)
        future = self._pool.submit(action)

        def completed(_: object) -> None:
            with self._state_lock:
                self._busy.discard(operation)
                if self._closing or self._closed:
                    return
            self.busy_changed.emit(operation, False)
            try:
                result = future.result()
                if not self._core_connected:
                    self._core_connected = True
                    self.connection_changed.emit(True)
                self.error_occurred.emit("")
                done(result)
            except Exception as error:
                if (
                    isinstance(error, CoreApiError)
                    and error.code == "runtime.unavailable"
                ):
                    self._core_connected = False
                    self.connection_changed.emit(False)
                elif isinstance(error, CoreApiError) and not self._core_connected:
                    self._core_connected = True
                    self.connection_changed.emit(True)
                self.error_occurred.emit(str(error))
            finally:
                if operation == "load" and self._bootstrap_pending:
                    self._bootstrap_pending = False
                    if self._core_connected:
                        self.load()

        future.add_done_callback(completed)

    def add_shutdown_callback(self, callback: Callable[[], None]) -> None:
        """Register an idempotent stop hook for an external UI worker."""
        with self._state_lock:
            if self._closing or self._closed:
                callback()
                return
            self._shutdown_callbacks.append(callback)

    def close(self) -> None:
        """Stop UI work exactly once; auxiliary disconnect logging is best effort."""
        with self._state_lock:
            if self._closing or self._closed:
                return
            self._closing = True
            callbacks = tuple(self._shutdown_callbacks)
            self._shutdown_callbacks.clear()
            self._bootstrap_pending = False

        try:
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    logger.exception("failed to stop Streaming Admin background worker")

            self._pool.shutdown(wait=True, cancel_futures=True)
            self._try_send_manual_disconnect_event()

            close_client = getattr(self.client, "close", None)
            if callable(close_client):
                try:
                    close_client()
                except Exception:
                    logger.exception("failed to close Streaming Admin Core API client")
        finally:
            with self._state_lock:
                self._closed = True
                self._closing = False
                self._busy.clear()

    def _is_stopping(self) -> bool:
        with self._state_lock:
            return self._closing or self._closed

    def _try_send_manual_disconnect_event(self) -> None:
        callback = getattr(self.client, "manual_check_ui_event", None)
        if not callable(callback):
            return
        try:
            callback("streaming_admin_disconnected", None)
        except (CoreApiError, httpx.HTTPError) as error:
            logger.debug("manual disconnect event was not delivered: %s", error)

    def _manual_event(self, event: str, details: dict[str, Any] | None = None) -> None:
        if self._is_stopping():
            return
        callback = getattr(self.client, "manual_check_ui_event", None)
        if callable(callback):
            callback(event, details)
