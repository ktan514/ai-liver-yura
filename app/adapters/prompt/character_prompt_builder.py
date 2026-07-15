from __future__ import annotations

import json
from dataclasses import asdict

from app.domain.character import CharacterProfile
from app.domain.character_response import ResponseContext


class CharacterPromptBuilder:
    """確定済み事実をキャラクター表現へ変換するrole専用PromptBuilder。"""

    def build(
        self,
        context: ResponseContext,
        *,
        character_profile: CharacterProfile | None,
        correction: str | None,
    ) -> str:
        lines = [
            "あなたはCharacter LLMです。行動判断や実行可否判断はしない。",
            "Character Profile: "
            + json.dumps(
                asdict(character_profile) if character_profile is not None else {},
                ensure_ascii=False,
                default=str,
            ),
            "次の確定済みResponse Contextだけを事実として表現する。",
            json.dumps(asdict(context), ensure_ascii=False, default=str),
            "allowed_claims以外を主張せず、forbidden_claimsを絶対に主張しない。",
            "JSONのみ返す: "
            '{"speech":"発話","expression":"smile","gesture":null,'
            '"claims":[{"claim_type":"conversation_only","activity_type":null,'
            '"operation":null,"status":null,"target":null,"confidence":1.0,'
            '"evidence":"発話中の根拠"}]}',
            "claimsはspeech本文が実際に主張している事実だけを記載する。",
        ]
        if correction:
            lines.append(f"前回応答の修正理由: {correction}")
        return "\n".join(lines)
