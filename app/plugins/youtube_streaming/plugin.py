from __future__ import annotations

from app.core.plugins import PluginContext


class StreamingPreparationPlugin:
    """配信準備Capabilityのprovider。配信開始Commandは意図的に持たない。"""

    _CAPABILITIES = frozenset(
        {
            "stream.session.prepare",
            "youtube.broadcast.resolve",
            "youtube.authentication",
            "youtube.broadcast.inspect",
            "youtube.live_chat.inspect",
            "youtube.stream.inspect",
            "obs.connect",
            "obs.inspect.output",
            "obs.inspect.scene",
            "obs.inspect.audio",
            "obs.inspect.avatar_source",
            "stream.session.start",
            "obs.stream.start",
            "youtube.broadcast.transition_live",
            "tts.speak",
            "avatar.control",
        }
    )

    @property
    def plugin_id(self) -> str:
        return "youtube_streaming"

    @property
    def display_name(self) -> str:
        return "YouTube Streaming Preparation"

    @property
    def capabilities(self) -> frozenset[str]:
        return self._CAPABILITIES

    def available_capabilities(self) -> frozenset[str]:
        return frozenset({"stream.session.prepare"})

    def initialize(self, context: PluginContext) -> None:
        del context

    def shutdown(self) -> None:
        return None
