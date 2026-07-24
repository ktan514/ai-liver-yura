from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class PronunciationRule:
    surface: str
    reading: str
    priority: int
    enabled: bool
    definition_order: int
    match_type: str = "literal"
    description: str | None = None


class PronunciationDictionary:
    """外部YAMLから安全なフレーズ読み補正ルールを読み込む。"""

    def __init__(self, rules: tuple[PronunciationRule, ...] = ()) -> None:
        self._rules = rules

    @property
    def rules(self) -> tuple[PronunciationRule, ...]:
        return self._rules

    @classmethod
    def load(cls, path: str | Path) -> PronunciationDictionary:
        dictionary_path = Path(path)
        logger = TraceLogger()
        if not dictionary_path.exists():
            logger.warning(
                "pronunciation_dictionary:load:missing",
                path=str(dictionary_path),
            )
            return cls()

        try:
            with dictionary_path.open("r", encoding="utf-8") as file:
                raw_data = yaml.safe_load(file)
        except (OSError, yaml.YAMLError) as error:
            logger.warning(
                "pronunciation_dictionary:load:failed",
                path=str(dictionary_path),
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return cls()

        if raw_data is None:
            return cls()
        if not isinstance(raw_data, dict) or not isinstance(
            raw_data.get("rules"), list
        ):
            logger.warning(
                "pronunciation_dictionary:load:invalid_root",
                path=str(dictionary_path),
            )
            return cls()

        valid_rules: list[PronunciationRule] = []
        for index, raw_rule in enumerate(raw_data["rules"]):
            rule = cls._parse_rule(raw_rule, index, logger)
            if rule is not None and rule.enabled:
                valid_rules.append(rule)

        ordered_rules = sorted(
            valid_rules,
            key=lambda rule: (
                -rule.priority,
                -len(rule.surface),
                rule.definition_order,
            ),
        )
        unique_rules: list[PronunciationRule] = []
        rules_by_surface: dict[str, PronunciationRule] = {}
        for rule in ordered_rules:
            existing = rules_by_surface.get(rule.surface)
            if existing is not None:
                reason = "duplicate" if existing.reading == rule.reading else "conflict"
                logger.warning(
                    f"pronunciation_dictionary:load:{reason}",
                    surface=rule.surface,
                    kept_reading=existing.reading,
                    ignored_reading=rule.reading,
                )
                continue
            rules_by_surface[rule.surface] = rule
            unique_rules.append(rule)
        return cls(tuple(unique_rules))

    @staticmethod
    def _parse_rule(
        raw_rule: Any,
        index: int,
        logger: TraceLogger,
    ) -> PronunciationRule | None:
        if not isinstance(raw_rule, dict):
            logger.warning("pronunciation_dictionary:rule:invalid", index=index)
            return None
        surface = raw_rule.get("surface")
        reading = raw_rule.get("reading")
        priority = raw_rule.get("priority")
        enabled = raw_rule.get("enabled")
        match_type = raw_rule.get("match_type", "literal")
        description = raw_rule.get("description")
        is_valid = (
            isinstance(surface, str)
            and bool(surface)
            and isinstance(reading, str)
            and bool(reading)
            and isinstance(priority, int)
            and not isinstance(priority, bool)
            and isinstance(enabled, bool)
            and match_type == "literal"
            and (description is None or isinstance(description, str))
        )
        if not is_valid:
            logger.warning(
                "pronunciation_dictionary:rule:invalid",
                index=index,
                surface=surface,
            )
            return None
        assert isinstance(surface, str)
        assert isinstance(reading, str)
        assert isinstance(priority, int) and not isinstance(priority, bool)
        assert isinstance(enabled, bool)
        return PronunciationRule(
            surface=surface,
            reading=reading,
            priority=priority,
            enabled=enabled,
            definition_order=index,
            match_type=match_type,
            description=description,
        )
