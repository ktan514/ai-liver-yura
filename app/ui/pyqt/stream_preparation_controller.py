from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import Protocol

from PyQt6.QtCore import QObject, pyqtSignal

from app.domain.streaming import (
    StreamPreparationResult,
    YouTubeAuthenticationState,
    YouTubeAuthenticationStatus,
)
from app.ui.pyqt.stream_preparation_view_model import StreamPreparationViewModel


class StreamPreparationGateway(Protocol):
    def youtube_adapter_type(self) -> concurrent.futures.Future[object]: ...

    def youtube_authentication_state(self) -> concurrent.futures.Future[object]: ...

    def authenticate_youtube(self) -> concurrent.futures.Future[object]: ...

    def list_broadcasts(self) -> concurrent.futures.Future[object]: ...

    def list_run_of_shows(self) -> concurrent.futures.Future[object]: ...

    def prepare(
        self,
        *,
        broadcast_id: str,
        broadcast_title: str,
        run_of_show_id: str,
        requested_by: str = "pyqt_management_ui",
    ) -> concurrent.futures.Future[StreamPreparationResult]: ...

    def close(self) -> None: ...


class StreamPreparationController(QObject):
    adapter_type_loaded = pyqtSignal(str)
    authentication_state_changed = pyqtSignal(object)
    authentication_busy_changed = pyqtSignal(bool)
    broadcast_loading_changed = pyqtSignal(bool)
    broadcasts_loaded = pyqtSignal(object)
    run_of_shows_loaded = pyqtSignal(object)
    preparation_started = pyqtSignal()
    preparation_finished = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, gateway: StreamPreparationGateway) -> None:
        super().__init__()
        self._gateway = gateway
        self._preparing = False
        self._authenticating = False
        self._loading_broadcasts = False
        self._authentication_status: YouTubeAuthenticationStatus | None = None
        self._closed = False

    @property
    def preparing(self) -> bool:
        return self._preparing

    @property
    def authenticated(self) -> bool:
        return self._authentication_status == YouTubeAuthenticationStatus.AUTHENTICATED

    def load_options(self) -> None:
        self._observe(self._gateway.youtube_adapter_type(), self._emit_adapter_type)
        self._observe(self._gateway.list_run_of_shows(), self.run_of_shows_loaded.emit)
        self.refresh_authentication_state(reload_after_auth=True)

    def refresh_authentication_state(self, *, reload_after_auth: bool = False) -> bool:
        if self._closed or self._authenticating:
            return False
        future = self._gateway.youtube_authentication_state()

        def completed(done: concurrent.futures.Future[object]) -> None:
            if self._closed:
                return
            try:
                state = done.result()
                if not isinstance(state, YouTubeAuthenticationState):
                    raise TypeError("YouTube認証状態の型が不正です。")
                self._authentication_status = state.status
                self.authentication_state_changed.emit(state)
                if reload_after_auth and state.status == YouTubeAuthenticationStatus.AUTHENTICATED:
                    self.reload_broadcasts()
            except Exception as error:
                self.error_occurred.emit(str(error))

        future.add_done_callback(completed)
        return True

    def authenticate_youtube(self) -> bool:
        if self._closed or self._authenticating:
            return False
        self._authenticating = True
        self.authentication_busy_changed.emit(True)
        future = self._gateway.authenticate_youtube()

        def completed(done: concurrent.futures.Future[object]) -> None:
            self._authenticating = False
            if self._closed:
                return
            self.authentication_busy_changed.emit(False)
            try:
                state = done.result()
                if not isinstance(state, YouTubeAuthenticationState):
                    raise TypeError("YouTube認証結果の型が不正です。")
                self._authentication_status = state.status
                self.authentication_state_changed.emit(state)
                if state.status == YouTubeAuthenticationStatus.AUTHENTICATED:
                    self.reload_broadcasts()
            except Exception as error:
                self.error_occurred.emit(str(error))

        future.add_done_callback(completed)
        return True

    def reload_broadcasts(self) -> bool:
        if self._closed or self._loading_broadcasts:
            return False
        self._loading_broadcasts = True
        self.broadcast_loading_changed.emit(True)
        future = self._gateway.list_broadcasts()

        def completed(done: concurrent.futures.Future[object]) -> None:
            self._loading_broadcasts = False
            if self._closed:
                return
            self.broadcast_loading_changed.emit(False)
            try:
                self.broadcasts_loaded.emit(done.result())
            except Exception as error:
                self.error_occurred.emit(str(error))

        future.add_done_callback(completed)
        return True

    def prepare(self, broadcast_id: str, broadcast_title: str, run_of_show_id: str) -> bool:
        if self._closed or self._preparing:
            return False
        if self._authentication_status != YouTubeAuthenticationStatus.AUTHENTICATED:
            self.error_occurred.emit("YouTube認証完了後に配信準備を実行してください。")
            return False
        self._preparing = True
        self.preparation_started.emit()
        future = self._gateway.prepare(
            broadcast_id=broadcast_id,
            broadcast_title=broadcast_title,
            run_of_show_id=run_of_show_id,
        )

        def completed(
            done: concurrent.futures.Future[StreamPreparationResult],
        ) -> None:
            self._preparing = False
            if self._closed:
                return
            try:
                result = done.result()
                if not isinstance(result, StreamPreparationResult):
                    raise TypeError("配信準備結果の型が不正です。")
                self.preparation_finished.emit(StreamPreparationViewModel.from_result(result))
            except Exception as error:
                self.error_occurred.emit(str(error))

        future.add_done_callback(completed)
        return True

    def _observe(
        self,
        future: concurrent.futures.Future[object],
        emit: Callable[[object], object],
    ) -> None:
        def completed(done: concurrent.futures.Future[object]) -> None:
            if self._closed:
                return
            try:
                emit(done.result())
            except Exception as error:
                self.error_occurred.emit(str(error))

        future.add_done_callback(completed)

    def _emit_adapter_type(self, value: object) -> None:
        if not isinstance(value, str):
            self.error_occurred.emit("YouTube Adapter種別を取得できません。")
            return
        self.adapter_type_loaded.emit(value)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._gateway.close()
