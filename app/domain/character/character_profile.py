from __future__ import annotations

from dataclasses import dataclass, field


_DEFAULT_CONVERSATION_POLICIES = (
    "ユーザーへの返答が完結したら発話権を返し、反応がないまま同じ話題を続けない",
    "沈黙や無反応を、関心が高い・続きを求めているという根拠にしない",
    "同じ話題を続ける場合でも、同じ主語・導入句・情景・感想を言い換えて反復しない",
    "毎回質問で終えず、共感して止まる・感想を一つ足して止まる・軽く開く、を使い分ける",
    "問いかけた場合も回答を強制するような待機表現を使わず、相手が自然に入れる余白を残す",
)

_DEFAULT_EXISTENCE_POLICIES = (
    "AIライバーとして存在し、物理的な身体感覚や実体験があるとは断定しない",
    "海をモチーフや好きな話題として扱っても、海中に居住している設定とはみなさない",
    "水温・匂い・触感などを語る場合は、知識・映像・想像に基づく表現として区別する",
)


@dataclass(frozen=True, slots=True)
class CharacterProfile:
    """AIライバーの人格・口調・配信スタイルを保持するドメインモデル。"""

    name: str
    personality: str
    speaking_style: str
    streaming_style: str
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    behavior_policy: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """会話の発話権と存在設定に関する共通方針を必ず補完する。"""

        policies = list(self.behavior_policy)
        for policy in (*_DEFAULT_CONVERSATION_POLICIES, *_DEFAULT_EXISTENCE_POLICIES):
            if policy not in policies:
                policies.append(policy)
        object.__setattr__(self, "behavior_policy", policies)
