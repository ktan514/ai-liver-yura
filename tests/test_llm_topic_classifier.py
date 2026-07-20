from __future__ import annotations

import pytest

from app.adapters.topic.llm_topic_classifier import LlmTopicClassifier
from app.domain.topic import TopicCategory


class FakeTopicClassificationModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.received_prompts: list[str] = []

    async def classify_topic(self, prompt: str) -> str:
        self.received_prompts.append(prompt)
        return self.response


@pytest.mark.asyncio
async def test_llm_topic_classifier_returns_category_from_model_response() -> None:
    model = FakeTopicClassificationModel(response="sea_life")
    classifier = LlmTopicClassifier(model=model)

    category = await classifier.classify(
        "透明な体でゆらゆら漂う生き物って不思議だよね。"
    )

    assert category == TopicCategory.SEA_LIFE


@pytest.mark.asyncio
async def test_llm_topic_classifier_accepts_response_with_surrounding_whitespace() -> (
    None
):
    model = FakeTopicClassificationModel(response="\n game \n")
    classifier = LlmTopicClassifier(model=model)

    category = await classifier.classify("探索して隠し通路を見つける瞬間が好きなんだ。")

    assert category == TopicCategory.GAME


@pytest.mark.asyncio
async def test_llm_topic_classifier_extracts_category_when_response_contains_extra_text() -> (
    None
):
    model = FakeTopicClassificationModel(response="カテゴリは technology です。")
    classifier = LlmTopicClassifier(model=model)

    category = await classifier.classify("モデルの仕組みを考えるのって面白いよね。")

    assert category == TopicCategory.TECHNOLOGY


@pytest.mark.asyncio
async def test_llm_topic_classifier_returns_other_when_response_is_unknown() -> None:
    model = FakeTopicClassificationModel(response="unknown_category")
    classifier = LlmTopicClassifier(model=model)

    category = await classifier.classify("今日は何となく窓の外を眺めていたよ。")

    assert category == TopicCategory.OTHER


@pytest.mark.asyncio
async def test_llm_topic_classifier_builds_prompt_with_categories_and_input_text() -> (
    None
):
    model = FakeTopicClassificationModel(response="streaming")
    classifier = LlmTopicClassifier(model=model)

    await classifier.classify("マイクの音量を少し調整してから話すね。")

    assert len(model.received_prompts) == 1
    prompt = model.received_prompts[0]
    assert "あなたはAIライバーの発話内容を話題カテゴリに分類する判定器です。" in prompt
    assert "# カテゴリ一覧" in prompt
    assert "- sea_life" in prompt
    assert "海の生物" in prompt
    assert "- nature" in prompt
    assert "自然環境" in prompt
    assert "- game" in prompt
    assert "- technology" in prompt
    assert "- streaming" in prompt
    assert "- mood" in prompt
    assert "感情や気分" in prompt
    assert "- viewer_question" in prompt
    assert "- other" in prompt
    assert "# 判定ルール" in prompt
    assert "- 出力はカテゴリIDのみ" in prompt
    assert "発話全体の主題" in prompt
    assert "波、海辺、潮風、空、雨、森、自然音、季節" in prompt
    assert "# 発話" in prompt
    assert "マイクの音量を少し調整してから話すね。" in prompt
