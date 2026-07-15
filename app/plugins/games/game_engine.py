"""Games Plugin内部のGameEngine公開点。

移行期間中は既存実装を再公開し、Core側はこの型を参照しない。
"""

from app.runtime.game_engine import GameEngine

__all__ = ["GameEngine"]
