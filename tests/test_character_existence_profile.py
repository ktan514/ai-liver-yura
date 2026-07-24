from app.domain.character.character_profile import (
    CharacterExistenceProfile,
    CharacterProfile,
)


def test_structured_existence_profile_is_reflected_in_behavior_policy() -> None:
    profile = CharacterProfile(
        name="ゆら",
        personality="好奇心が強い",
        speaking_style="やわらかい",
        streaming_style="自然体",
        existence=CharacterExistenceProfile(
            existence_type="AI VTuber",
            home_environment="仮想空間",
            world_relationship="海が好きだが海中居住者ではない",
        ),
    )

    assert "存在種別はAI VTuberである" in profile.behavior_policy
    assert "主な存在環境は仮想空間である" in profile.behavior_policy
    assert "海が好きだが海中居住者ではない" in profile.behavior_policy
    assert any("直接経験したとは断定しない" in item for item in profile.behavior_policy)
