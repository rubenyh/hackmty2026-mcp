"""Safe conversion of common PostgreSQL values to JSON-compatible data."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def to_json_safe(value: Any) -> Any:
    """Recursively convert database values without leaking implementation details."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return to_json_safe(value.value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, Mapping):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [to_json_safe(item) for item in value]
    return str(value)


def serialize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a SQLAlchemy row mapping into a JSON-safe dictionary."""
    return {str(key): to_json_safe(value) for key, value in row.items()}
