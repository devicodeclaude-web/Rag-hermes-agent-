from __future__ import annotations

from typing import Any


def _condition(payload: dict[str, Any], condition: dict[str, Any]) -> bool:
    if "must" in condition or "min_should" in condition:
        return payload_matches_filter(payload, condition)
    key = condition.get("key")
    if not isinstance(key, str) or key not in payload or payload[key] is None:
        return False
    value = payload[key]
    if "match" in condition:
        match = condition["match"]
        if "value" in match:
            return value == match["value"]
        if "any" in match:
            candidates = value if isinstance(value, list) else [value]
            return bool(set(candidates).intersection(match["any"]))
        return False
    if "range" in condition and "lte" in condition["range"]:
        try:
            return value <= condition["range"]["lte"]
        except TypeError:
            return False
    return False


def payload_matches_filter(payload: dict[str, Any], query_filter: dict[str, Any]) -> bool:
    """Small Qdrant-filter semantics oracle used only by differential tests."""
    if not all(_condition(payload, item) for item in query_filter.get("must", [])):
        return False
    minimum = query_filter.get("min_should")
    if minimum is not None:
        conditions = minimum.get("conditions", [])
        count = sum(_condition(payload, item) for item in conditions)
        if count < int(minimum.get("min_count", 1)):
            return False
    return True
