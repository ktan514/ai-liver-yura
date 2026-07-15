from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UserRequestKind(str, Enum):
    EXECUTION = "execution"
    KNOWLEDGE = "knowledge"
    PAST_EVENT = "past_event"
    NEGATIVE = "negative"
    CHAT = "chat"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class UserRequestInterpretation:
    kind: UserRequestKind
    confidence: float
    reason: str


def interpret_user_request(text: str) -> UserRequestInterpretation:
    """対象機能を列挙せず、発話が行為の実行要求かどうかだけを判定する。"""

    normalized = text.strip()
    if not normalized:
        return UserRequestInterpretation(UserRequestKind.AMBIGUOUS, 0.0, "empty_input")

    if any(marker in normalized for marker in ("したくない", "しないで", "やめて", "不要")):
        return UserRequestInterpretation(UserRequestKind.NEGATIVE, 0.95, "negative_expression")
    if any(marker in normalized for marker in ("昨日", "さっき", "この前", "以前")) and any(
        marker in normalized for marker in ("した", "やった", "していた", "だった")
    ):
        return UserRequestInterpretation(UserRequestKind.PAST_EVENT, 0.9, "past_expression")
    hypothetical = any(
        marker in normalized for marker in ("としたら", "とすれば", "仮に")
    ) or normalized.startswith("もし")
    if hypothetical:
        return UserRequestInterpretation(UserRequestKind.CHAT, 0.9, "hypothetical_expression")
    if any(
        marker in normalized
        for marker in (
            "って何",
            "とは",
            "どんな",
            "方法を教えて",
            "について教えて",
            "ルールを教えて",
            "ルール教えて",
            "は難しい",
            "って難しい",
        )
    ):
        return UserRequestInterpretation(UserRequestKind.KNOWLEDGE, 0.9, "knowledge_question")
    if normalized.endswith(
        (
            "して",
            "してよ",
            "してください",
            "してほしい",
            "お願い",
            "始めよう",
            "やろう",
            "しよう",
            "遊ぼう",
            "しませんか？",
            "しませんか?",
            "しない？",
            "しない?",
            "しようか",
            "しようか？",
            "しようか?",
            "付き合って",
            "聞いて",
            "見て",
            "たい",
        )
    ):
        return UserRequestInterpretation(UserRequestKind.EXECUTION, 0.85, "action_request")
    return UserRequestInterpretation(UserRequestKind.CHAT, 0.7, "ordinary_conversation")
