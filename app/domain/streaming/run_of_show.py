from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunOfShowSummary:
    run_of_show_id: str
    title: str
    planned_duration_seconds: int
    segment_count: int
    source_path: str
    version: str
