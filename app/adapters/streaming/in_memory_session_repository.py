from __future__ import annotations

from threading import RLock

from app.domain.streaming import StreamSession, StreamSessionStatus


class InMemoryStreamSessionRepository:
    def __init__(self) -> None:
        self._sessions: dict[str, StreamSession] = {}
        self._lock = RLock()

    def create(self, session: StreamSession) -> StreamSession:
        with self._lock:
            active = self.find_active_or_preparing()
            if active is not None and active.session_id != session.session_id:
                raise ValueError("準備中または準備済みのStreamSessionが既に存在します。")
            if session.session_id in self._sessions:
                raise ValueError(f"StreamSessionは作成済みです: {session.session_id}")
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> StreamSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def save(self, session: StreamSession) -> StreamSession:
        with self._lock:
            current = self._sessions.get(session.session_id)
            if current is None:
                raise ValueError(f"未知のStreamSessionです: {session.session_id}")
            if session.state_version != current.state_version + 1:
                raise ValueError("StreamSessionのstate_versionは1ずつ進めてください。")
            self._sessions[session.session_id] = session
            return session

    def find_active_or_preparing(self) -> StreamSession | None:
        with self._lock:
            return next(
                (
                    item
                    for item in self._sessions.values()
                    if item.status
                    in {
                        StreamSessionStatus.CREATED,
                        StreamSessionStatus.PREPARING,
                        StreamSessionStatus.READY,
                        StreamSessionStatus.START_APPROVED,
                        StreamSessionStatus.STARTING,
                        StreamSessionStatus.START_FAILED,
                        StreamSessionStatus.LIVE,
                        StreamSessionStatus.CLOSING_REQUESTED,
                        StreamSessionStatus.CLOSING,
                        StreamSessionStatus.STOPPING,
                        StreamSessionStatus.EMERGENCY_STOP_REQUESTED,
                        StreamSessionStatus.EMERGENCY_STOPPING,
                        StreamSessionStatus.STOP_FAILED,
                    }
                ),
                None,
            )
