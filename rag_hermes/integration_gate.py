from __future__ import annotations

from typing import Any


def assert_no_skipped_integration_tests(result: Any, *, expected_tests: int) -> None:
    if result.skipped:
        raise RuntimeError(f"integration tests skipped: {result.skipped!r}")
