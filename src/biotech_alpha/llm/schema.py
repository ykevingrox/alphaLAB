"""Lightweight JSON-schema-style validator for structured LLM outputs.

The project keeps its own validator instead of pulling in ``jsonschema`` so
the LLM adapter stays dependency-light and error messages remain focused
on the agent/prompt context.

Supported schema keys per object:

* ``type``: ``"object"``, ``"array"``, ``"string"``, ``"integer"``,
  ``"number"``, ``"boolean"``, ``"null"`` or a list of those.
* ``required``: list of property names required on an ``object``.
* ``properties``: mapping of property name to sub-schema.
* ``items``: sub-schema applied to every element of an ``array``.
* ``min_items`` / ``max_items``: bounds for arrays.
* ``enum``: list of allowed scalar values.
* ``min_length`` / ``max_length``: bounds for strings.
"""

from __future__ import annotations

from typing import Any


class SchemaError(ValueError):
    """Raised when a decoded value does not satisfy the expected schema."""


def validate_json_schema(
    value: Any, schema: dict[str, Any], *, path: str = "$"
) -> None:
    """Validate ``value`` against ``schema``; raise :class:`SchemaError` on mismatch."""

    expected = schema.get("type")
    if expected is not None:
        _check_type(value, expected, path)

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(
            f"{path}: expected one of {schema['enum']!r}, got {value!r}"
        )

    if isinstance(value, str):
        _check_string_bounds(value, schema, path)
    if isinstance(value, list):
        _check_array(value, schema, path)
    if isinstance(value, dict):
        _check_object(value, schema, path)


def _check_type(value: Any, expected: Any, path: str) -> None:
    expected_list = expected if isinstance(expected, list) else [expected]
    for option in expected_list:
        if _matches_type(value, option):
            return
    raise SchemaError(
        f"{path}: expected type {expected!r}, got {type(value).__name__}"
    )


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise SchemaError(f"unsupported schema type {expected!r}")


def _check_string_bounds(value: str, schema: dict[str, Any], path: str) -> None:
    min_length = schema.get("min_length")
    if isinstance(min_length, int) and len(value) < min_length:
        raise SchemaError(
            f"{path}: string shorter than min_length={min_length}"
        )
    max_length = schema.get("max_length")
    if isinstance(max_length, int) and len(value) > max_length:
        raise SchemaError(
            f"{path}: string longer than max_length={max_length}"
        )


def _check_array(value: list[Any], schema: dict[str, Any], path: str) -> None:
    min_items = schema.get("min_items")
    if isinstance(min_items, int) and len(value) < min_items:
        raise SchemaError(
            f"{path}: array has {len(value)} items, min_items={min_items}"
        )
    max_items = schema.get("max_items")
    if isinstance(max_items, int) and len(value) > max_items:
        raise SchemaError(
            f"{path}: array has {len(value)} items, max_items={max_items}"
        )
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            validate_json_schema(
                item, item_schema, path=f"{path}[{index}]"
            )


def _check_object(value: dict[str, Any], schema: dict[str, Any], path: str) -> None:
    required = schema.get("required") or []
    for key in required:
        if key not in value:
            raise SchemaError(f"{path}: missing required key {key!r}")
    properties = schema.get("properties") or {}
    for key, sub_schema in properties.items():
        if key not in value:
            continue
        if not isinstance(sub_schema, dict):
            continue
        validate_json_schema(value[key], sub_schema, path=f"{path}.{key}")
