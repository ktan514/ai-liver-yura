"""Streaming run-of-show domain models."""

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


@dataclass(frozen=True, slots=True)
class RunOfShowSegment:
    segment_id: str
    segment_type: str
    title: str
    duration_seconds: int
    required: bool
    script_mode: str
    prompt_template_id: str
    order: int = 0
    intent: str | None = None
    topic: str | None = None
