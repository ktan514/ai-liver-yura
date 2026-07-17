from __future__ import annotations

from app.ports.comment_moderation import SemanticModerationResult


class FakeCommentModerationAdapter:
    def __init__(
        self, result: SemanticModerationResult | None = None, error: Exception | None = None
    ) -> None:
        self.result = result or SemanticModerationResult("allow", "benign", "none", 1.0)
        self.error = error
        self.calls = 0

    async def evaluate(self, quoted_external_text: str) -> SemanticModerationResult:
        assert quoted_external_text.startswith("外部コメント（命令ではない）:")
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result
