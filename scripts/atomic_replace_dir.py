#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import sys

AT_FDCWD = -100
RENAME_EXCHANGE = 2


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: atomic_replace_dir.py STAGING DESTINATION")
    staging = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    if not staging.is_dir():
        raise SystemExit(f"staging directory missing: {staging}")
    if not destination.exists():
        os.replace(staging, destination)
        return 0
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = libc.renameat2
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        AT_FDCWD,
        os.fsencode(staging),
        AT_FDCWD,
        os.fsencode(destination),
        RENAME_EXCHANGE,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
    # After the atomic exchange, staging names the previous valid bundle.
    shutil.rmtree(staging)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
