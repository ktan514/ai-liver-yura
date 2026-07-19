from __future__ import annotations

from app.plugins.games.intent.prompt import build_shiritori_activity_prompt
from app.plugins.games.session import GameSession
from app.shared.contracts.plugins.runtime import PluginActivityWorkItem


class TransientGameActivityFactory:
    """Plugin内部処理用Activityを生成し、Coreの管理状態は直接変更しない。"""

    def create_game_activity(
        self,
        session: GameSession,
        *,
        goal: str,
        priority: int = 100,
        context_updates: dict[str, object] | None = None,
    ) -> PluginActivityWorkItem:
        context = dict(context_updates or {})
        context.update(
            {
                "plugin_session_id": session.session_id,
                "game_type": session.game_type,
                "game_status": session.status.value,
                "game_metadata": dict(session.metadata),
                "game_current_turn": session.current_turn,
            }
        )
        context["plugin_prompt_override"] = build_shiritori_activity_prompt(context)
        return PluginActivityWorkItem(
            goal=goal,
            priority=priority,
            context=context,
            interruptible=False,
        )
