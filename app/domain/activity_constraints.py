from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

ConstraintSchema: TypeAlias = dict[str, object]


@dataclass(frozen=True, slots=True)
class ConstraintValidationError:
    path: str
    code: str
    message: str
    expected: object | None = None
    actual: object | None = None


@dataclass(frozen=True, slots=True)
class ValidatedConstraints(Mapping[str, object]):
    data: dict[str, object]
    schema_version: str

    def __getitem__(self, key: str) -> object:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class ConstraintValidationResult:
    valid: bool
    normalized_constraints: dict[str, object]
    errors: tuple[ConstraintValidationError, ...] = ()
    warnings: tuple[str, ...] = ()
    applied_defaults: dict[str, object] = field(default_factory=dict)
    removed_fields: tuple[str, ...] = ()
    schema_version: str = "1"

    def as_validated(self) -> ValidatedConstraints | None:
        if not self.valid:
            return None
        return ValidatedConstraints(dict(self.normalized_constraints), self.schema_version)


class LegacyConstraintSchemaAdapter:
    """Deprecatedな`{name: type}`形式を共通object schemaへ変換する。"""

    _schema_keywords = frozenset(
        {
            "type",
            "properties",
            "required",
            "additionalProperties",
            "enum",
            "items",
            "oneOf",
            "anyOf",
            "nullable",
        }
    )

    def adapt(self, schema: Mapping[str, object]) -> tuple[ConstraintSchema, tuple[str, ...]]:
        if self._schema_keywords.intersection(schema):
            return dict(schema), ()
        if not schema:
            return {"type": "object", "additionalProperties": True}, ()
        properties = {
            str(name): {"type": type_name}
            for name, type_name in schema.items()
            if isinstance(type_name, str)
        }
        return (
            {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
            },
            ("legacy_constraint_schema_deprecated",),
        )


class ActivityConstraintValidator:
    """Activity非依存のJSON Schema互換サブセットを再帰検証する。"""

    def __init__(self, adapter: LegacyConstraintSchemaAdapter | None = None) -> None:
        self._adapter = adapter or LegacyConstraintSchemaAdapter()

    def validate(
        self,
        constraints: Mapping[str, object],
        schema: Mapping[str, object],
        *,
        schema_version: str = "1",
    ) -> ConstraintValidationResult:
        normalized_schema, warnings = self._adapter.adapt(schema)
        errors: list[ConstraintValidationError] = []
        defaults: dict[str, object] = {}
        normalized = self._validate_value(
            dict(constraints), normalized_schema, "", errors, defaults
        )
        values = normalized if isinstance(normalized, dict) else dict(constraints)
        return ConstraintValidationResult(
            valid=not errors,
            normalized_constraints=values,
            errors=tuple(errors),
            warnings=warnings,
            applied_defaults=defaults,
            schema_version=schema_version,
        )

    def _validate_value(
        self,
        value: object,
        schema: Mapping[str, object],
        path: str,
        errors: list[ConstraintValidationError],
        defaults: dict[str, object],
    ) -> object:
        if value is None and bool(schema.get("nullable", False)):
            return None
        expected = schema.get("type")
        expected_types = (
            tuple(str(item) for item in expected)
            if isinstance(expected, list)
            else (str(expected),)
            if expected is not None
            else ()
        )
        if expected_types and not any(self._matches_type(value, item) for item in expected_types):
            self._error(errors, path, "invalid_type", expected, self._actual_type(value))
            return value
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            self._error(errors, path, "enum", enum, value)
        if isinstance(value, str):
            minimum = schema.get("minLength")
            maximum = schema.get("maxLength")
            if isinstance(minimum, int) and len(value) < minimum:
                self._error(errors, path, "min_length", minimum, len(value))
            if isinstance(maximum, int) and len(value) > maximum:
                self._error(errors, path, "max_length", maximum, len(value))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if isinstance(minimum, (int, float)) and value < minimum:
                self._error(errors, path, "minimum", minimum, value)
            if isinstance(maximum, (int, float)) and value > maximum:
                self._error(errors, path, "maximum", maximum, value)
        if isinstance(value, list):
            minimum = schema.get("minItems")
            maximum = schema.get("maxItems")
            if isinstance(minimum, int) and len(value) < minimum:
                self._error(errors, path, "min_items", minimum, len(value))
            if isinstance(maximum, int) and len(value) > maximum:
                self._error(errors, path, "max_items", maximum, len(value))
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                return [
                    self._validate_value(
                        item, item_schema, self._join(path, str(index)), errors, defaults
                    )
                    for index, item in enumerate(value)
                ]
        if isinstance(value, dict):
            return self._validate_object(value, schema, path, errors, defaults)
        return value

    def _validate_object(
        self,
        value: dict[object, object],
        schema: Mapping[str, object],
        path: str,
        errors: list[ConstraintValidationError],
        defaults: dict[str, object],
    ) -> dict[str, object]:
        properties_value = schema.get("properties", {})
        properties = properties_value if isinstance(properties_value, dict) else {}
        required_value = schema.get("required", [])
        required = required_value if isinstance(required_value, list) else []
        normalized = {str(key): item for key, item in value.items()}
        for name in required:
            if isinstance(name, str) and name not in normalized:
                field_schema = properties.get(name)
                if isinstance(field_schema, dict) and "default" in field_schema:
                    normalized[name] = field_schema["default"]
                    defaults[self._join(path, name)] = field_schema["default"]
                else:
                    self._error(errors, self._join(path, str(name)), "required", True, None)
        for name, field_schema in properties.items():
            if not isinstance(name, str) or not isinstance(field_schema, dict):
                continue
            if name not in normalized and "default" in field_schema:
                normalized[name] = field_schema["default"]
                defaults[self._join(path, name)] = field_schema["default"]
            if name in normalized:
                normalized[name] = self._validate_value(
                    normalized[name], field_schema, self._join(path, name), errors, defaults
                )
        additional = schema.get("additionalProperties", True)
        for name in tuple(normalized):
            if name in properties:
                continue
            if additional is False:
                self._error(errors, self._join(path, name), "additional_property", False, name)
            elif isinstance(additional, dict):
                normalized[name] = self._validate_value(
                    normalized[name], additional, self._join(path, name), errors, defaults
                )
        return normalized

    @staticmethod
    def _matches_type(value: object, expected: str) -> bool:
        return {
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
            "null": value is None,
        }.get(expected, False)

    @staticmethod
    def _actual_type(value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return type(value).__name__

    @staticmethod
    def _join(path: str, name: str) -> str:
        return f"{path}.{name}" if path else name

    @staticmethod
    def _error(
        errors: list[ConstraintValidationError],
        path: str,
        code: str,
        expected: object,
        actual: object,
    ) -> None:
        errors.append(
            ConstraintValidationError(
                path=path or "$",
                code=code,
                message=f"constraint validation failed: {code}",
                expected=expected,
                actual=actual,
            )
        )
