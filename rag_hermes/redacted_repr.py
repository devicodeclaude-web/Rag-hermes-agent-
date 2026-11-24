"""Render counts in a redacted `repr` without formatting an untrusted value.

A public frozen dataclass can be rebuilt with arbitrary fields by
`dataclasses.replace`, `object.__new__`, `pickle` or `deepcopy`. A `repr`
written to keep evidence out of a log line must therefore never interpolate a
field it has not type-checked: a forged counter's `__format__` prints whatever
it wants — newlines and ANSI escapes included, which fabricate log lines — or
raises in the middle of formatting a traceback and hides the real error.

Shared on purpose: the divergence plan renderer and the audited G1 result types
must not drift apart, since each claims the same representation policy.
"""
from __future__ import annotations

from typing import Any

REDACTED = "<invalide>"


def safe_count(value: Any) -> str:
    """Render a count without invoking formatting on an untrusted object.

    `type(value) is int` rather than `isinstance`: `isinstance(True, int)` is
    true, and `True` is not a count.
    """
    if type(value) is int and 0 <= value <= 1_000_000_000_000:
        return str(value)
    return REDACTED


def safe_length(value: Any) -> str:
    """Render the length of a field DECLARED as a tuple, forged or not.

    `len()` on a forged field either raises (an int) or reports the length of
    something else entirely (a string's characters), so the exact type is
    checked before measuring.
    """
    if type(value) is not tuple:
        return REDACTED
    return safe_count(len(value))
