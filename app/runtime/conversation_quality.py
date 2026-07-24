from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from app.domain.conversation_flow import SpeechRecord


@dataclass(frozen=True, slots=True)
class RepetitionAssessment:
    repeated: bool
    score: float
    reasons: tuple[str, ...]


class ConversationRepetitionDetector:
    """文字列だけでなく発話目的・主語・情景の重複も検出する。"""

    def __init__(self, threshold: float = 0.68) -> None:
        self._threshold = threshold

    def assess(
        self,
        candidate: SpeechRecord,
        history: list[SpeechRecord],
    ) -> RepetitionAssessment:
        if not history:
            return RepetitionAssessment(False, 0.0, ())
        best_score = 0.0
        best_reasons: tuple[str, ...] = ()
        for previous in history[-5:]:
            reasons: list[str] = []
            score = SequenceMatcher(
                None,
                self._normalize(previous.text),
                self._normalize(candidate.text),
            ).ratio() * 0.35
            if previous.purpose == candidate.purpose:
                score += 0.20
                reasons.append("same_purpose")
            if previous.topic and previous.topic == candidate.topic:
                score += 0.15
                reasons.append("same_topic")
            if previous.subject and previous.subject == candidate.subject:
                score += 0.15
                reasons.append("same_subject")
            if previous.sentiment and previous.sentiment == candidate.sentiment:
                score += 0.05
                reasons.append("same_sentiment")
            imagery_overlap = self._overlap(previous.imagery, candidate.imagery)
            score += imagery_overlap * 0.10
            if imagery_overlap >= 0.5:
                reasons.append("same_imagery")
            if score > best_score:
                best_score = score
                best_reasons = tuple(reasons)
        return RepetitionAssessment(
            repeated=best_score >= self._threshold,
            score=min(best_score, 1.0),
            reasons=best_reasons,
        )

    @staticmethod
    def _normalize(text: str) -> str:
        return "".join(text.lower().split())

    @staticmethod
    def _overlap(left: tuple[str, ...], right: tuple[str, ...]) -> float:
        if not left or not right:
            return 0.0
        left_set = set(left)
        right_set = set(right)
        return len(left_set & right_set) / max(len(left_set | right_set), 1)


@dataclass(frozen=True, slots=True)
class ConversationQualitySnapshot:
    consecutive_agent_turns: int
    seconds_since_user_input: float | None
    same_topic_turns: int
    semantic_similarity: float
    speech_purpose: str | None
    handoff_state: str
    autonomous_resume_reason: str | None

    def as_trace_fields(self) -> dict[str, object]:
        return {
            "consecutive_agent_turns": self.consecutive_agent_turns,
            "seconds_since_user_input": self.seconds_since_user_input,
            "same_topic_turns": self.same_topic_turns,
            "semantic_similarity": self.semantic_similarity,
            "speech_purpose": self.speech_purpose,
            "handoff_state": self.handoff_state,
            "autonomous_resume_reason": self.autonomous_resume_reason,
        }
