from __future__ import annotations

from typing import Protocol

from app.domain.topic import TopicCategory
from app.domain.topic_classifier import TopicClassifier


class TopicClassificationModel(Protocol):
    async def classify_topic(self, prompt: str) -> str:
        raise NotImplementedError


class LlmTopicClassifier(TopicClassifier):
    def __init__(self, model: TopicClassificationModel) -> None:
        self._model = model

    async def classify(self, text: str) -> TopicCategory:
        response = await self._model.classify_topic(self._build_prompt(text))
        return self._parse_category(response)

    def _build_prompt(self, text: str) -> str:
        categories = "\n".join(
            [
                "- sea_life: クラゲ、イルカ、深海魚、水族館、魚など、海の生物に関する話題",
                "- nature: 海、波、空、森、雨、風、自然音、季節など、自然環境に関する話題",
                "- game: ゲーム、ゲーム実況、ゲーム作品、プレイ体験に関する話題",
                "- technology: AI、プログラミング、機械、ガジェット、技術に関する話題",
                "- streaming: 配信活動、コメント、視聴者、チャンネル運営、OBSに関する話題",
                "- mood: 眠い、楽しい、落ち着く、緊張する、ワクワクするなど、"
                "感情や気分そのものに関する話題",
                "- viewer_question: 視聴者からの質問、相談、問いかけに答える話題",
                "- other: どれにも明確に当てはまらない話題",
            ]
        )

        return "\n".join(
            [
                "あなたはAIライバーの発話内容を話題カテゴリに分類する判定器です。",
                "次のカテゴリ一覧から最も近いカテゴリを1つだけ選び、カテゴリIDだけを出力してください。",
                "",
                "# カテゴリ一覧",
                categories,
                "",
                "# 判定ルール",
                "- 出力はカテゴリIDのみ",
                "- 説明文、理由、補足は出力しない",
                "- 複数カテゴリに見える場合は、発話の中心テーマを優先する",
                "- 視聴者への問いかけが中心の場合は viewer_question を選ぶ",
                "- 配信そのもの、マイク、画面、コメント、OBSに関する話は streaming を選ぶ",
                "- ゲーム、操作、探索、ステージ、攻略に関する話は game を選ぶ",
                "- AI、技術、モデル、仕組み、実装に関する話は technology を選ぶ",
                "- 気分、感情、体調、雰囲気そのものが中心なら mood を選ぶ",
                "- クラゲ、イルカ、魚、深海魚、水族館など、海の生物が中心なら sea_life を選ぶ",
                "- 波、海辺、潮風、空、雨、森、自然音、季節など、自然環境が中心なら nature を選ぶ",
                "- どれにも明確に当てはまらない場合は other を選ぶ",
                "",
                "# 発話",
                text,
            ]
        )

    def _parse_category(self, response: str) -> TopicCategory:
        normalized_response = response.strip().lower()

        for category in TopicCategory:
            if normalized_response == category.value:
                return category

        for category in TopicCategory:
            if category.value in normalized_response:
                return category

        return TopicCategory.OTHER
