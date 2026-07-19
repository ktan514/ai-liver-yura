from __future__ import annotations

from typing import Any, Protocol


class StreamingRuntimeComponents(Protocol):
    """Plugin-owned view of objects supplied by the composition root."""

    config: Any
    usecase: Any
    sessions: Any
    publisher: Any
    capability_registry: Any
    start_usecase: Any
    openings: Any
    main_segments: Any
    run_of_show: Any
    obs_control: Any
    youtube_control: Any
    live_chat: Any
