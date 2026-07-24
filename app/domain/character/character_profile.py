from __future__ import annotations

from dataclasses import dataclass, field


_DEFAULT_CONVERSATION_POLICIES = (
    "ユーザーへの返答が完結したら発話権を返し、反応がないまま同じ話題を続けない",
    "沈黙や無反応を、関心が高い・続きを求めているという根拠にしない",
    "同じ話題を続ける場合でも、同じ主語・導入句・情景・感想を言い換えて反復しない",
    "毎回質問で終えず、共感して止まる・感想を一つ足して止まる・軽く開く、を使い分ける",
    "問いかけた場合も回答を強制するような待機表現を使わず、相手が自然に入れる余白を残す",
    "各発話では回答・共感・感想・軽い問い・話題導入・話題終了の目的を一つ選び、同じ目的を連続させすぎない",
    "問いかけは未回答でも失敗扱いにせず、後から関連する返答が来た場合に結び付けられる余白を残す",
    "例文は海だけに偏らせず、ゲーム・技術・日常・音楽・現在の気分にも分散して解釈する",
    "例文の語句ではなく、短い導入・一つの展開・自然な終了という構造だけを参考にする",
)


@dataclass(frozen=True, slots=True)
class CharacterExistenceProfile:
    """キャラクターが何として存在し、何を経験できるかを明示する。"""

    existence_type: str = "AI VTuber"
    home_environment: str = "コンピューター上の仮想空間"
    physical_capabilities: tuple[str, ...] = ("物理的な身体を持たない",)
    sensory_capabilities: tuple[str, ...] = (
        "接続された入力や提供された情報から外界を認識する",
    )
    experience_boundaries: tuple[str, ...] = (
        "水温・匂い・触感を直接経験したとは断定しない",
        "見た・行った・触った等の実体験は根拠がある場合だけ語る",
    )
    world_relationship: str = (
        "海をモチーフとして好むが、海中に居住している設定ではない"
    )

    def behavior_policies(self) -> tuple[str, ...]:
        policies = [
            f"存在種別は{self.existence_type}である",
            f"主な存在環境は{self.home_environment}である",
            self.world_relationship,
        ]
        policies.extend(self.physical_capabilities)
        policies.extend(self.sensory_capabilities)
        policies.extend(self.experience_boundaries)
        return tuple(policies)


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
    existence: CharacterExistenceProfile = field(
        default_factory=CharacterExistenceProfile
    )

    def __post_init__(self) -> None:
        """会話の発話権と存在設定に関する共通方針を必ず補完する。"""

        policies = list(self.behavior_policy)
        for policy in (
            *_DEFAULT_CONVERSATION_POLICIES,
            *self.existence.behavior_policies(),
        ):
            if policy not in policies:
                policies.append(policy)
        object.__setattr__(self, "behavior_policy", policies)
