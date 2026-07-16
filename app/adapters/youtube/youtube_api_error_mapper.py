from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httplib2  # type: ignore[import-untyped]
from google.auth.exceptions import TransportError
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]


class YouTubeApiErrorKind(str, Enum):
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMIT = "rate_limit"
    DAILY_LIMIT = "daily_limit"
    UNKNOWN_QUOTA = "unknown_quota"
    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True, slots=True)
class YouTubeApiError(RuntimeError):
    kind: YouTubeApiErrorKind
    safe_message: str
    retryable: bool = False
    http_status: int | None = None
    api_reason: str | None = None

    def __str__(self) -> str:
        return self.safe_message


class YouTubeApiErrorMapper:
    _QUOTA_EXHAUSTED = {"quotaExceeded", "quotaExceeded402"}
    _DAILY_LIMIT = {"dailyLimitExceeded", "dailyLimitExceededUnreg"}
    _RATE_LIMIT = {"rateLimitExceeded", "userRateLimitExceeded"}
    _AUTH_REASONS = {"authError", "invalidCredentials", "required"}

    @classmethod
    def map(cls, error: BaseException) -> YouTubeApiError:
        if isinstance(error, YouTubeApiError):
            return error
        if isinstance(error, (TimeoutError, socket.timeout)):
            return YouTubeApiError(
                YouTubeApiErrorKind.TIMEOUT,
                "YouTube API requestがtimeoutしました。",
                retryable=True,
            )
        if isinstance(error, HttpError):
            return cls._from_http_error(error)
        if isinstance(error, (OSError, httplib2.HttpLib2Error, TransportError)):
            return YouTubeApiError(
                YouTubeApiErrorKind.NETWORK,
                "YouTube APIへ接続できません。",
                retryable=True,
            )
        return YouTubeApiError(
            YouTubeApiErrorKind.INVALID_RESPONSE,
            "YouTube API responseの処理に失敗しました。",
        )

    @classmethod
    def _from_http_error(cls, error: HttpError) -> YouTubeApiError:
        status = int(getattr(error.resp, "status", 0)) or None
        reason = cls._extract_reason(error)
        if status == 401:
            return cls._error(
                YouTubeApiErrorKind.AUTHENTICATION,
                "YouTube OAuth認証が無効です。",
                status,
                reason,
            )
        if reason in cls._QUOTA_EXHAUSTED:
            return cls._error(
                YouTubeApiErrorKind.QUOTA_EXHAUSTED,
                "YouTube API quotaを使い切りました。",
                status,
                reason,
            )
        if reason in cls._DAILY_LIMIT:
            return cls._error(
                YouTubeApiErrorKind.DAILY_LIMIT,
                "YouTube APIの日次上限へ到達しました。",
                status,
                reason,
            )
        if reason in cls._RATE_LIMIT or status == 429:
            return cls._error(
                YouTubeApiErrorKind.RATE_LIMIT,
                "YouTube APIのrate limitへ到達しました。",
                status,
                reason,
            )
        if reason in cls._AUTH_REASONS:
            return cls._error(
                YouTubeApiErrorKind.AUTHENTICATION,
                "YouTube OAuth認証が無効です。",
                status,
                reason,
            )
        if status == 403:
            if reason and "quota" in reason.lower():
                kind = YouTubeApiErrorKind.UNKNOWN_QUOTA
                message = "YouTube API quotaに関するエラーが発生しました。"
            else:
                kind = YouTubeApiErrorKind.PERMISSION
                message = "YouTube APIの権限が不足しています。"
            return cls._error(kind, message, status, reason)
        if status == 404:
            return cls._error(
                YouTubeApiErrorKind.NOT_FOUND,
                "YouTubeの対象が見つかりません。",
                status,
                reason,
            )
        if status == 409:
            return cls._error(
                YouTubeApiErrorKind.INVALID_STATE,
                "YouTubeの現在状態では処理できません。",
                status,
                reason,
            )
        if status is not None and status >= 500:
            return YouTubeApiError(
                YouTubeApiErrorKind.SERVER,
                "YouTube APIで一時的なサーバーエラーが発生しました。",
                retryable=True,
                http_status=status,
                api_reason=reason,
            )
        return cls._error(
            YouTubeApiErrorKind.INVALID_RESPONSE,
            "YouTube API requestに失敗しました。",
            status,
            reason,
        )

    @staticmethod
    def _extract_reason(error: HttpError) -> str | None:
        try:
            raw: Any = json.loads(error.content.decode("utf-8"))
            errors = raw.get("error", {}).get("errors", [])
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                reason = errors[0].get("reason")
                return reason if isinstance(reason, str) else None
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return None
        return None

    @staticmethod
    def _error(
        kind: YouTubeApiErrorKind,
        message: str,
        status: int | None,
        reason: str | None,
    ) -> YouTubeApiError:
        return YouTubeApiError(
            kind,
            message,
            retryable=False,
            http_status=status,
            api_reason=reason,
        )
