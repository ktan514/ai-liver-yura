from app.domain.conversation_flow import SpeechPurpose, SpeechRecord
from app.runtime.conversation_quality import ConversationRepetitionDetector


def test_detects_semantic_structure_repetition() -> None:
    detector = ConversationRepetitionDetector(threshold=0.60)
    previous = SpeechRecord(
        text="海の光がゆらゆらして落ち着くね。",
        purpose=SpeechPurpose.SHARE_REACTION,
        topic="海",
        subject="光",
        sentiment="落ち着く",
        imagery=("ゆらめき", "光"),
    )
    candidate = SpeechRecord(
        text="水面から差す明かりって静かな気分になるなあ。",
        purpose=SpeechPurpose.SHARE_REACTION,
        topic="海",
        subject="光",
        sentiment="落ち着く",
        imagery=("光", "ゆらめき"),
    )

    result = detector.assess(candidate, [previous])

    assert result.repeated is True
    assert "same_purpose" in result.reasons
    assert "same_subject" in result.reasons
    assert "same_imagery" in result.reasons


def test_allows_different_purpose_and_subject() -> None:
    detector = ConversationRepetitionDetector()
    previous = SpeechRecord(
        text="海の光がきれいだね。",
        purpose=SpeechPurpose.SHARE_REACTION,
        topic="海",
        subject="光",
    )
    candidate = SpeechRecord(
        text="ところで、最近遊んだゲームはある？",
        purpose=SpeechPurpose.ASK_LIGHT_QUESTION,
        topic="ゲーム",
        subject="遊んだゲーム",
    )

    assert detector.assess(candidate, [previous]).repeated is False
