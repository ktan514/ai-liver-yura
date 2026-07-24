from app.core.plugins.user_request import UserRequestKind, interpret_user_request


def test_execution_requests_are_identified_without_feature_ids() -> None:
    for text in (
        "しりとりしよう",
        "今日の最新ニュースを検索して",
        "私の声を聞いて",
        "一緒に星間航行シミュレーションを始めよう",
    ):
        assert interpret_user_request(text).kind == UserRequestKind.EXECUTION


def test_knowledge_past_and_negative_statements_are_not_execution_requests() -> None:
    assert (
        interpret_user_request("しりとりってどんな遊び？").kind
        == UserRequestKind.KNOWLEDGE
    )
    assert (
        interpret_user_request("昨日しりとりをした").kind == UserRequestKind.PAST_EVENT
    )
    assert (
        interpret_user_request("しりとりはしたくない").kind == UserRequestKind.NEGATIVE
    )
    assert interpret_user_request("今日はいい天気だね").kind == UserRequestKind.CHAT
