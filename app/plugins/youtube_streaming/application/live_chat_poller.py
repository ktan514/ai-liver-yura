from __future__ import annotations

import asyncio
import hashlib
import random
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.plugins.youtube_streaming.application.lifecycle_gate import StreamLifecycleGate
from app.plugins.youtube_streaming.domain import (
    LifecycleOperation,
    LiveChatPollerState,
    LiveChatPollingStatus,
    NormalizedLiveChatMessage,
)
from app.ports.youtube_errors import YouTubeApiError, YouTubeApiErrorKind
from app.ports.youtube_live_chat import (
    LiveChatDeduplicationRepository,
    LiveChatMessageDto,
    YouTubeLiveChatReadPort,
)
from app.shared.contracts.plugins.runtime import PluginEvent

EventSink = Callable[[PluginEvent], Awaitable[None]]
PollerPublisher = Callable[[str, dict[str, object], str], None]


class BoundedLiveChatDeduplicationRepository:
    def __init__(self, capacity_per_session: int) -> None:
        self._capacity = capacity_per_session
        self._seen: dict[str, OrderedDict[str, None]] = {}

    def check_and_mark(self, session_id: str, key: str) -> bool:
        cache = self._seen.setdefault(session_id, OrderedDict())
        if key in cache:
            cache.move_to_end(key)
            return False
        cache[key] = None
        while len(cache) > self._capacity:
            cache.popitem(last=False)
        return True


class YouTubeLiveChatPoller:
    def __init__(
        self,
        *,
        session_id: str,
        trace_id: str,
        broadcast_id: str,
        live_chat_id: str,
        adapter: YouTubeLiveChatReadPort,
        gate: StreamLifecycleGate,
        event_sink: EventSink,
        publisher: PollerPublisher | None = None,
        max_results: int = 200,
        max_messages_per_poll: int = 100,
        max_events_per_second: int = 20,
        dedup_capacity: int = 10_000,
        deduplication: LiveChatDeduplicationRepository | None = None,
        buffer_capacity: int = 500,
        max_retries: int = 3,
    ) -> None:
        self.session_id = session_id
        self.trace_id = trace_id
        self._broadcast_id = broadcast_id
        self._live_chat_id = live_chat_id
        self._adapter = adapter
        self._gate = gate
        self._sink = event_sink
        self._publish = publisher or (lambda _event, _data, _trace: None)
        self._max_results = max_results
        self._max_per_poll = max_messages_per_poll
        self._max_per_second = max_events_per_second
        self._dedup = deduplication or BoundedLiveChatDeduplicationRepository(
            dedup_capacity
        )
        self._buffer_capacity = buffer_capacity
        self._max_retries = max_retries
        self._next_token: str | None = None
        self._status = LiveChatPollingStatus(session_id, LiveChatPollerState.IDLE.value)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @property
    def status(self) -> LiveChatPollingStatus:
        return self._status

    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return False
        decision = self._gate.evaluate(
            LifecycleOperation.START_COMMENT_POLLING,
            self.session_id,
            trace_id=self.trace_id,
        )
        if not decision.allowed:
            self._stop_for_lifecycle(decision.reason_code)
            return False
        self._status = replace(self._status, status=LiveChatPollerState.STARTING.value)
        self._task = asyncio.create_task(self.run())
        return True

    async def run(self) -> None:
        self._status = replace(self._status, status=LiveChatPollerState.RUNNING.value)
        self._emit_status("stream_comments.polling_started")
        while not self._stop.is_set():
            if not await self.poll_once():
                break
            await asyncio.sleep(max(self._status.current_interval_ms, 100) / 1000)

    async def poll_once(self) -> bool:
        decision = self._gate.evaluate(
            LifecycleOperation.CONTINUE_COMMENT_POLLING,
            self.session_id,
            trace_id=self.trace_id,
        )
        if not decision.allowed:
            self._stop_for_lifecycle(decision.reason_code)
            return False
        attempt = self._status.attempt + 1
        self._status = replace(self._status, attempt=attempt)
        try:
            page = await self._adapter.list_messages(
                self._live_chat_id, self._next_token, self._max_results
            )
        except Exception as error:
            return await self._handle_error(error)
        decision = self._gate.evaluate(
            LifecycleOperation.CONTINUE_COMMENT_POLLING,
            self.session_id,
            trace_id=self.trace_id,
        )
        if not decision.allowed:
            self._stop_for_lifecycle(decision.reason_code)
            return False
        received_at = datetime.now(timezone.utc)
        try:
            normalized = [
                self._normalize(item, received_at)
                for item in page.messages
                if item.message_id and isinstance(item.snippet, dict)
            ]
        except (TypeError, ValueError) as error:
            return await self._handle_error(error)
        normalized.sort(key=lambda item: (item.published_at, item.message_id))
        unique: list[NormalizedLiveChatMessage] = []
        duplicate = 0
        for message in normalized:
            key = f"youtube:{self._broadcast_id}:{message.message_id}"
            if not self._dedup.check_and_mark(self.session_id, key):
                duplicate += 1
                self._publish(
                    "stream_comments.message_deduplicated",
                    {
                        "session_id": self.session_id,
                        "message_id_hash": hashlib.sha256(
                            message.message_id.encode()
                        ).hexdigest()[:12],
                        "deduplicated": True,
                    },
                    self.trace_id,
                )
                continue
            unique.append(message)
        capacity = min(self._max_per_poll, self._buffer_capacity)
        if len(unique) > capacity:
            preferred = sorted(unique, key=self._priority, reverse=True)[:capacity]
            selected_ids = {item.message_id for item in preferred}
            dropped = len(unique) - len(preferred)
            unique = [item for item in unique if item.message_id in selected_ids]
        else:
            dropped = 0
        emitted = 0
        per_poll_rate = max(1, self._max_per_second)
        for message in unique[:per_poll_rate]:
            decision = self._gate.evaluate(
                LifecycleOperation.CONTINUE_COMMENT_POLLING,
                self.session_id,
                trace_id=self.trace_id,
            )
            if not decision.allowed:
                self._stop_for_lifecycle(decision.reason_code)
                return False
            await self._sink(self._event(message))
            emitted += 1
        dropped += max(0, len(unique) - per_poll_rate)
        self._next_token = page.next_page_token
        self._status = replace(
            self._status,
            status=LiveChatPollerState.RUNNING.value,
            last_success_at=received_at,
            last_message_at=max(
                (item.published_at for item in unique),
                default=self._status.last_message_at,
            ),
            received_count=self._status.received_count + len(normalized),
            emitted_count=self._status.emitted_count + emitted,
            duplicate_count=self._status.duplicate_count + duplicate,
            dropped_count=self._status.dropped_count + dropped,
            current_interval_ms=page.polling_interval_ms,
            failure_code=None,
            retryable=False,
        )
        if emitted:
            self._publish(
                "stream_comments.message_received",
                {
                    "session_id": self.session_id,
                    "count": emitted,
                    "message_types": sorted(
                        {item.message_type for item in unique[:per_poll_rate]}
                    ),
                },
                self.trace_id,
            )
        if dropped:
            self._publish(
                "stream_comments.message_dropped",
                {"session_id": self.session_id, "count": dropped},
                self.trace_id,
            )
        return True

    async def _handle_error(self, error: Exception) -> bool:
        code, retryable, ended = self._classify_error(error)
        if ended:
            self._status = replace(
                self._status,
                status=LiveChatPollerState.STOPPED.value,
                failure_code=code,
                retryable=False,
            )
            self._emit_status("stream_comments.polling_stopped")
            return False
        if retryable and self._status.attempt <= self._max_retries:
            interval = min(
                60_000,
                int(
                    1000 * 2 ** max(0, self._status.attempt - 1)
                    + random.uniform(0, 250)
                ),
            )
            self._status = replace(
                self._status,
                status=LiveChatPollerState.BACKING_OFF.value,
                current_interval_ms=interval,
                failure_code=code,
                retryable=True,
            )
            self._emit_status("stream_comments.polling_backoff")
            return True
        self._status = replace(
            self._status,
            status=LiveChatPollerState.FAILED.value,
            failure_code=code,
            retryable=retryable,
        )
        self._emit_status("stream_comments.polling_failed")
        return False

    def stop(self, reason: str = "lifecycle.operation_not_allowed") -> None:
        self._stop.set()
        self._stop_for_lifecycle(reason)

    def _stop_for_lifecycle(self, reason: str | None) -> None:
        self._status = replace(
            self._status,
            status=LiveChatPollerState.STOPPED.value,
            failure_code="live_chat.lifecycle_blocked",
            retryable=False,
            lifecycle_stop_reason=reason,
        )
        self._emit_status("stream_comments.polling_stopped")

    def _event(self, message: NormalizedLiveChatMessage) -> PluginEvent:
        priority = (
            80
            if message.is_paid or message.author_role in {"owner", "moderator"}
            else 40
        )
        return PluginEvent(
            event_type="youtube_comment",
            payload={
                "session_id": message.session_id,
                "message_id": message.message_id,
                "platform": message.platform,
                "author": {
                    "channel_id": message.author_channel_id,
                    "display_name": message.author_display_name,
                    "role": message.author_role,
                },
                "comment": message.text,
                "message_type": message.message_type,
                "is_paid": message.is_paid,
                "is_deleted": message.is_deleted,
                "amount_display": message.amount_display,
                "currency": message.currency,
                "published_at": message.published_at.isoformat(),
                "received_at": message.received_at.isoformat(),
                "moderation_status": "not_evaluated",
            },
            priority=priority,
            discardable=False,
            trace_id=self.trace_id,
        )

    def _normalize(
        self, item: LiveChatMessageDto, received_at: datetime
    ) -> NormalizedLiveChatMessage:
        snippet, author = item.snippet, item.author
        kind = item.kind
        type_map = {
            "textMessageEvent": "text",
            "superChatEvent": "super_chat",
            "superStickerEvent": "super_sticker",
            "newSponsorEvent": "membership",
            "memberMilestoneChatEvent": "membership",
            "membershipGiftingEvent": "membership_gift",
            "giftMembershipReceivedEvent": "membership_gift",
            "messageDeletedEvent": "deleted",
            "userBannedEvent": "system",
            "tombstone": "system",
        }
        role = (
            "owner"
            if author.get("isChatOwner")
            else (
                "moderator"
                if author.get("isChatModerator")
                else (
                    "member"
                    if author.get("isChatSponsor")
                    else (
                        "verified"
                        if author.get("isVerified")
                        else "viewer" if author else "unknown"
                    )
                )
            )
        )
        details = (
            snippet.get("superChatDetails") or snippet.get("superStickerDetails") or {}
        )
        published = self._parse_time(snippet.get("publishedAt"))
        text = snippet.get("displayMessage")
        return NormalizedLiveChatMessage(
            item.message_id,
            self.session_id,
            "youtube",
            self._broadcast_id,
            str(author.get("channelId")) if author.get("channelId") else None,
            str(author.get("displayName") or ""),
            role,
            str(text) if isinstance(text, str) else None,
            published,
            received_at,
            type_map.get(kind, "unknown"),
            kind in {"messageDeletedEvent", "userBannedEvent", "tombstone"},
            kind in {"superChatEvent", "superStickerEvent"},
            (
                str(details.get("amountDisplayString"))
                if details.get("amountDisplayString")
                else None
            ),
            str(details.get("currency")) if details.get("currency") else None,
            kind,
        )

    @staticmethod
    def _parse_time(value: Any) -> datetime:
        if not isinstance(value, str):
            raise ValueError("live_chat.invalid_response")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _priority(message: NormalizedLiveChatMessage) -> int:
        return (
            3
            if message.author_role == "owner"
            else 2 if message.is_paid or message.author_role == "moderator" else 1
        )

    @staticmethod
    def _classify_error(error: Exception) -> tuple[str, bool, bool]:
        text = str(error)
        if "chat_ended" in text or "liveChatEnded" in text:
            return "live_chat.chat_ended", False, True
        if isinstance(error, YouTubeApiError):
            mapping = {
                YouTubeApiErrorKind.AUTHENTICATION: "live_chat.auth_failed",
                YouTubeApiErrorKind.PERMISSION: "live_chat.forbidden",
                YouTubeApiErrorKind.QUOTA_EXHAUSTED: "live_chat.quota_exceeded",
                YouTubeApiErrorKind.TIMEOUT: "live_chat.network_timeout",
                YouTubeApiErrorKind.NETWORK: "live_chat.transient_error",
                YouTubeApiErrorKind.SERVER: "live_chat.transient_error",
                YouTubeApiErrorKind.NOT_FOUND: "live_chat.not_found",
            }
            return (
                mapping.get(error.kind, "live_chat.invalid_response"),
                error.retryable,
                False,
            )
        if isinstance(error, (TimeoutError, OSError)):
            return "live_chat.network_timeout", True, False
        return "live_chat.invalid_response", False, False

    def _emit_status(self, event: str) -> None:
        digest = hashlib.sha256(self._broadcast_id.encode()).hexdigest()[:12]
        self._publish(
            event,
            {
                "session_id": self.session_id,
                "status": self._status.status,
                "broadcast_id_hash": digest,
                "attempt": self._status.attempt,
                "received_count": self._status.received_count,
                "emitted_count": self._status.emitted_count,
                "duplicate_count": self._status.duplicate_count,
                "dropped_count": self._status.dropped_count,
                "polling_interval_ms": self._status.current_interval_ms,
                "failure_code": self._status.failure_code,
            },
            self.trace_id,
        )
