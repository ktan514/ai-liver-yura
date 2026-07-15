from __future__ import annotations

from dataclasses import dataclass

from app.domain.behavior import (
    ActivityMatcherContext,
    ActivityOperation,
    DeterministicActivityMatch,
)


@dataclass(frozen=True, slots=True)
class ExactActivityPhraseMatcher:
    """Games Pluginが所有する高精度な開始・停止表現Matcher。"""

    start_phrases: tuple[str, ...]
    stop_phrases: tuple[str, ...]
    display_name: str
    continue_phrases: tuple[str, ...] = ()

    def match(self, context: ActivityMatcherContext) -> DeterministicActivityMatch | None:
        normalized = context.normalized_input
        if normalized in self.start_phrases:
            return DeterministicActivityMatch(
                operation=ActivityOperation.START,
                goal=f"{self.display_name}を開始する",
                confidence=0.99,
                reason="plugin_high_precision_start_match",
                evidence=normalized,
                matcher_id="games.shiritori.exact_phrase",
                matcher_type="plugin",
                priority=300,
            )
        if normalized in self.stop_phrases:
            return DeterministicActivityMatch(
                operation=ActivityOperation.STOP,
                goal=f"{self.display_name}を停止する",
                confidence=0.99,
                reason="plugin_high_precision_stop_match",
                evidence=normalized,
                matcher_id="games.shiritori.exact_phrase",
                matcher_type="plugin",
                priority=300,
            )
        if normalized in self.continue_phrases:
            return DeterministicActivityMatch(
                operation=ActivityOperation.CONTINUE,
                goal=f"{self.display_name}を継続する",
                confidence=0.99,
                reason="plugin_high_precision_continue_match",
                evidence=normalized,
                matcher_id="games.shiritori.exact_phrase",
                matcher_type="plugin",
                priority=300,
            )
        return None
