#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re

_DIGEST_LINE = re.compile(
    r"(?:[^\s:]+: )?digest: (sha256:[0-9a-f]{64}) size: [0-9]+"
)


def parse_push_digest(output: str) -> str:
    matches = [
        match.group(1)
        for line in output.splitlines()
        if (match := _DIGEST_LINE.fullmatch(line)) is not None
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one pushed digest, found {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract exactly one immutable digest from docker push output."
    )
    parser.add_argument("push_output", type=Path)
    arguments = parser.parse_args()
    output = arguments.push_output.read_text(encoding="utf-8")
    print(parse_push_digest(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
