from __future__ import annotations

from dataclasses import dataclass

from app.adapters.tts.pronunciation_dictionary import PronunciationDictionary


@dataclass(frozen=True, slots=True)
class AppliedPronunciationRule:
    surface: str
    reading: str
    replacement_count: int


@dataclass(frozen=True, slots=True)
class PronunciationCorrectionResult:
    original_text: str
    corrected_text: str
    applied_rules: tuple[AppliedPronunciationRule, ...]


class PronunciationCorrector:
    """優先順位を保ちながら元テキストへ非重複のフレーズ補正を適用する。"""

    def __init__(self, dictionary: PronunciationDictionary) -> None:
        self._dictionary = dictionary

    def correct(self, text: str) -> PronunciationCorrectionResult:
        corrected_parts: list[str] = []
        replacement_counts: dict[int, int] = {}
        position = 0
        while position < len(text):
            matched = False
            for rule_index, rule in enumerate(self._dictionary.rules):
                if text.startswith(rule.surface, position):
                    corrected_parts.append(rule.reading)
                    replacement_counts[rule_index] = (
                        replacement_counts.get(rule_index, 0) + 1
                    )
                    position += len(rule.surface)
                    matched = True
                    break
            if not matched:
                corrected_parts.append(text[position])
                position += 1

        applied_rules = tuple(
            AppliedPronunciationRule(
                surface=self._dictionary.rules[index].surface,
                reading=self._dictionary.rules[index].reading,
                replacement_count=count,
            )
            for index, count in replacement_counts.items()
        )
        return PronunciationCorrectionResult(
            original_text=text,
            corrected_text="".join(corrected_parts),
            applied_rules=applied_rules,
        )
