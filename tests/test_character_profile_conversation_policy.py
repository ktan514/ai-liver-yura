from app.domain.character import CharacterProfile


def test_character_profile_adds_turn_handoff_and_existence_policies() -> None:
    profile = CharacterProfile(
        name="星波ゆら",
        personality="明るい",
        speaking_style="親しみやすい",
        streaming_style="自然に会話する",
        behavior_policy=["短く返答する"],
    )

    assert "短く返答する" in profile.behavior_policy
    assert any("発話権を返し" in item for item in profile.behavior_policy)
    assert any("沈黙や無反応" in item for item in profile.behavior_policy)
    assert any("海中に居住" in item for item in profile.behavior_policy)
    assert any("物理的な身体感覚" in item for item in profile.behavior_policy)


def test_character_profile_does_not_duplicate_default_policies() -> None:
    policy = "沈黙や無反応を、関心が高い・続きを求めているという根拠にしない"
    profile = CharacterProfile(
        name="星波ゆら",
        personality="明るい",
        speaking_style="親しみやすい",
        streaming_style="自然に会話する",
        behavior_policy=[policy],
    )

    assert profile.behavior_policy.count(policy) == 1
