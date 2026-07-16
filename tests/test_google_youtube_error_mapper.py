from __future__ import annotations

import json

import httplib2  # type: ignore[import-untyped]
import pytest
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from app.adapters.youtube import YouTubeApiErrorKind, YouTubeApiErrorMapper


def http_error(status: int, reason: str) -> HttpError:
    response = httplib2.Response({"status": str(status)})
    content = json.dumps(
        {"error": {"errors": [{"reason": reason}], "message": "secret detail"}}
    ).encode()
    return HttpError(response, content)


@pytest.mark.parametrize(
    ("status", "reason", "kind", "retryable"),
    [
        (401, "authError", YouTubeApiErrorKind.AUTHENTICATION, False),
        (403, "authError", YouTubeApiErrorKind.AUTHENTICATION, False),
        (403, "forbidden", YouTubeApiErrorKind.PERMISSION, False),
        (403, "quotaExceeded", YouTubeApiErrorKind.QUOTA_EXHAUSTED, False),
        (403, "dailyLimitExceeded", YouTubeApiErrorKind.DAILY_LIMIT, False),
        (403, "rateLimitExceeded", YouTubeApiErrorKind.RATE_LIMIT, False),
        (404, "notFound", YouTubeApiErrorKind.NOT_FOUND, False),
        (409, "conflict", YouTubeApiErrorKind.INVALID_STATE, False),
        (429, "tooManyRequests", YouTubeApiErrorKind.RATE_LIMIT, False),
        (500, "backendError", YouTubeApiErrorKind.SERVER, True),
    ],
)
def test_http_error_mapping(
    status: int,
    reason: str,
    kind: YouTubeApiErrorKind,
    retryable: bool,
) -> None:
    mapped = YouTubeApiErrorMapper.map(http_error(status, reason))
    assert mapped.kind == kind
    assert mapped.retryable is retryable
    assert "secret detail" not in str(mapped)


def test_timeout_and_network_are_retryable() -> None:
    assert YouTubeApiErrorMapper.map(TimeoutError()).kind == YouTubeApiErrorKind.TIMEOUT
    assert YouTubeApiErrorMapper.map(OSError()).kind == YouTubeApiErrorKind.NETWORK
