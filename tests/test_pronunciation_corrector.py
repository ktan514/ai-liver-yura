from __future__ import annotations

from pathlib import Path

from app.adapters.tts.pronunciation_corrector import PronunciationCorrector
from app.adapters.tts.pronunciation_dictionary import (
    PronunciationDictionary,
    PronunciationRule,
)


def _rule(
    surface: str,
    reading: str,
    *,
    priority: int = 100,
    order: int = 0,
) -> PronunciationRule:
    return PronunciationRule(
        surface=surface,
        reading=reading,
        priority=priority,
        enabled=True,
        definition_order=order,
    )


def test_corrects_contextual_phrase() -> None:
    corrector = PronunciationCorrector(
        PronunciationDictionary((_rule("どんな風に", "どんなふうに"),))
    )

    result = corrector.correct("どんな風に話せばいいかな")

    assert result.original_text == "どんな風に話せばいいかな"
    assert result.corrected_text == "どんなふうに話せばいいかな"


def test_does_not_change_same_kanji_outside_registered_phrase() -> None:
    corrector = PronunciationCorrector(
        PronunciationDictionary((_rule("どんな風に", "どんなふうに"),))
    )

    result = corrector.correct("強い風が吹く")

    assert result.corrected_text == "強い風が吹く"
    assert result.applied_rules == ()


def test_higher_priority_rule_is_applied_first() -> None:
    dictionary = PronunciationDictionary(
        (
            _rule("東京", "とうきょう", priority=100),
            _rule("東京湾", "とうきょうわん", priority=50, order=1),
        )
    )

    result = PronunciationCorrector(dictionary).correct("東京湾")

    assert result.corrected_text == "とうきょう湾"


def test_longer_phrase_is_applied_first_for_same_priority(tmp_path: Path) -> None:
    dictionary_path = tmp_path / "dictionary.yaml"
    dictionary_path.write_text(
        """rules:
  - surface: "東京"
    reading: "とうきょう"
    priority: 100
    enabled: true
  - surface: "東京湾"
    reading: "とうきょうわん"
    priority: 100
    enabled: true
""",
        encoding="utf-8",
    )

    result = PronunciationCorrector(
        PronunciationDictionary.load(dictionary_path)
    ).correct("東京湾")

    assert result.corrected_text == "とうきょうわん"


def test_disabled_rule_is_not_loaded(tmp_path: Path) -> None:
    dictionary_path = tmp_path / "dictionary.yaml"
    dictionary_path.write_text(
        """rules:
  - surface: "人気"
    reading: "にんき"
    priority: 100
    enabled: false
""",
        encoding="utf-8",
    )

    dictionary = PronunciationDictionary.load(dictionary_path)

    assert dictionary.rules == ()


def test_unmatched_text_is_unchanged() -> None:
    corrector = PronunciationCorrector(
        PronunciationDictionary((_rule("人気", "にんき"),))
    )

    result = corrector.correct("今日はいい天気です")

    assert result.corrected_text == result.original_text


def test_missing_dictionary_returns_original_text(tmp_path: Path) -> None:
    dictionary = PronunciationDictionary.load(tmp_path / "missing.yaml")

    result = PronunciationCorrector(dictionary).correct("どんな風に話そう")

    assert result.corrected_text == "どんな風に話そう"


def test_invalid_rule_does_not_discard_valid_rule(tmp_path: Path) -> None:
    dictionary_path = tmp_path / "dictionary.yaml"
    dictionary_path.write_text(
        """rules:
  - surface: "どんな風に"
    reading: "どんなふうに"
    priority: 100
    enabled: true
  - surface: "壊れたルール"
    priority: high
    enabled: true
""",
        encoding="utf-8",
    )

    result = PronunciationCorrector(
        PronunciationDictionary.load(dictionary_path)
    ).correct("どんな風に話そう")

    assert result.corrected_text == "どんなふうに話そう"


def test_result_records_applied_rule_and_replacement_count() -> None:
    corrector = PronunciationCorrector(
        PronunciationDictionary((_rule("人気", "にんき"),))
    )

    result = corrector.correct("人気の人気商品")

    assert len(result.applied_rules) == 1
    assert result.applied_rules[0].surface == "人気"
    assert result.applied_rules[0].reading == "にんき"
    assert result.applied_rules[0].replacement_count == 2


def test_conflicting_surface_keeps_higher_priority_rule(tmp_path: Path) -> None:
    dictionary_path = tmp_path / "dictionary.yaml"
    dictionary_path.write_text(
        """rules:
  - surface: "行って"
    reading: "いって"
    priority: 10
    enabled: true
  - surface: "行って"
    reading: "おこなって"
    priority: 100
    enabled: true
""",
        encoding="utf-8",
    )

    dictionary = PronunciationDictionary.load(dictionary_path)

    assert len(dictionary.rules) == 1
    assert dictionary.rules[0].reading == "おこなって"
