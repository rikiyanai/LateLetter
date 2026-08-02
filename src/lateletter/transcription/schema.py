"""Stable JSON serialization and strict record decoding."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from enum import Enum
from typing import Any, TypeVar

from .hashing import require_sha256, safe_relative_path
from .versions import SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS

T = TypeVar("T")


class SchemaError(ValueError):
    """Raised when a record violates the canonical schema."""


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize with no whitespace or platform-dependent ordering."""

    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def record_to_dict(record: Any, *, include_output_hash: bool = True) -> dict[str, Any]:
    if not dataclasses.is_dataclass(record):
        raise TypeError("record_to_dict requires a dataclass record")
    result = _jsonable(record)
    if not isinstance(result, dict):  # pragma: no cover - dataclasses are mappings here
        raise TypeError("record did not serialize to an object")
    if not include_output_hash:
        result.pop("output_hash", None)
    return result


def record_from_dict(record_type: type[T], payload: Mapping[str, Any]) -> T:
    """Strictly decode one known record type, rejecting unknown/stale fields."""

    if not isinstance(payload, Mapping):
        raise SchemaError("record must be a JSON object")
    fields = {field.name: field for field in dataclasses.fields(record_type)}
    unknown = set(payload) - set(fields)
    if unknown:
        raise SchemaError(f"unknown record fields: {', '.join(sorted(unknown))}")
    missing = {
        name
        for name in fields
        if fields[name].default is dataclasses.MISSING and fields[name].default_factory is dataclasses.MISSING
        and name not in payload
    }
    if missing:
        raise SchemaError(f"missing record fields: {', '.join(sorted(missing))}")
    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaError(f"unsupported schema_version: {schema_version!r}")
    if "output_hash" not in payload:
        raise SchemaError("output_hash is required when reading a record")
    require_sha256(payload["output_hash"], field="output_hash")
    for key in ("input_hashes",):
        hashes = payload.get(key)
        if not isinstance(hashes, Mapping):
            raise SchemaError(f"{key} must be an object")
        for name, value in hashes.items():
            require_sha256(value, field=f"input_hashes.{name}")
    for key, value in payload.items():
        if key.endswith("_path") or key == "path" or key == "source_path":
            if value is not None:
                safe_relative_path(value, field=key)
    try:
        record = record_type(**dict(payload))
    except (TypeError, ValueError) as exc:
        raise SchemaError(str(exc)) from exc
    expected = getattr(record, "output_hash", "")
    if expected != payload["output_hash"]:
        raise SchemaError("output_hash does not match canonical record content")
    return record
