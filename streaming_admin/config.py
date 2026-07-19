from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdminClientConfig:
    base_url: str = "http://127.0.0.1:8765"
    token: str | None = None
    timeout_seconds: float = 10.0
    operator: str = "operator"

    @classmethod
    def from_environment(cls) -> AdminClientConfig:
        return cls(
            base_url=os.getenv(
                "AI_LIVER_ADMIN_API_URL", "http://127.0.0.1:8765"
            ).rstrip("/"),
            token=os.getenv("AI_LIVER_ADMIN_API_TOKEN"),
            timeout_seconds=float(os.getenv("AI_LIVER_ADMIN_API_TIMEOUT", "10")),
            operator=os.getenv("AI_LIVER_ADMIN_OPERATOR", "operator"),
        )
