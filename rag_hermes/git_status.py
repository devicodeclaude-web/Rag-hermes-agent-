"""Pure helpers to interpret ``git status --porcelain=v1`` output.

The evaluation report regenerates its own versioned output files, so a naive
``git status`` check always reports the working tree as dirty while the report
is being produced. ``working_tree_dirty_excluding`` lets a caller ignore the
exact output paths it is about to (re)write, so the ``working_tree_dirty`` field
honestly reflects whether anything *else* is uncommitted.
"""
from __future__ import annotations

from collections.abc import Iterable


def _entry_paths(entry: str) -> tuple[str, ...]:
    """Return the path(s) referenced by one porcelain=v1 line.

    Each line is ``XY <path>`` or, for renames/copies, ``XY <old> -> <new>``.
    The status field is two columns followed by a space.
    """
    body = entry[3:] if len(entry) > 3 else ""
    if " -> " in body:
        old, new = body.split(" -> ", 1)
        return (old.strip(), new.strip())
    return (body.strip(),)


def working_tree_dirty_excluding(
    porcelain_output: str, *, excluded: Iterable[str]
) -> bool:
    """True if any tracked/untracked change exists outside ``excluded`` paths.

    ``porcelain_output`` is the raw stdout of ``git status --porcelain=v1``.
    ``excluded`` are repo-relative paths whose changes must be ignored (the
    report artifacts the caller is regenerating). A porcelain line is ignored
    only when every path it references is excluded.
    """
    excluded_set = {path.strip() for path in excluded if path.strip()}
    for line in porcelain_output.splitlines():
        if not line.strip():
            continue
        paths = _entry_paths(line)
        if not paths or paths == ("",):
            continue
        if all(path in excluded_set for path in paths if path):
            continue
        return True
    return False
