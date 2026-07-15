from __future__ import annotations

import json
from dataclasses import asdict

from app.domain.character_response import CharacterResponse, Claim, ResponseContext


class ResponseValidatorPromptBuilder:
    """実行事実とCharacter Responseの整合だけを評価するrole専用PromptBuilder。"""

    def build(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        extracted_claims: tuple[Claim, ...] = (),
    ) -> str:
        return "\n".join(
            [
                "あなたはResponse Validatorです。表現の事実整合性だけを評価する。",
                "Response Context: " + json.dumps(asdict(context), ensure_ascii=False, default=str),
                "Character Response: "
                + json.dumps(asdict(response), ensure_ascii=False, default=str),
                "Speechから独立抽出済みのClaims: "
                + json.dumps(
                    [asdict(claim) for claim in extracted_claims],
                    ensure_ascii=False,
                    default=str,
                ),
                "決定論的検証済みの事実を変更せず、曖昧・婉曲・比喩表現から"
                "追加の事実Claimを独立抽出する。",
                "ActivityDefinitionにないActivityや、実行Resultにない成功事実を追加しない。",
                "JSONのみ返す: "
                '{"accepted":true,"reason":"facts_consistent","extracted_claims":['
                '{"claim_type":"conversation_only","activity_type":null,'
                '"operation":null,"status":null,"target":null,"confidence":0.9,'
                '"evidence":"発話中の根拠"}]}',
            ]
        )
