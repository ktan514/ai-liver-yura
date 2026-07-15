from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class ActivityResult:
    """発話に限定しないActivityの実行結果。"""

    result_type: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    succeeded: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
