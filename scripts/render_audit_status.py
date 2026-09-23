#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_hermes.audit_status import derive_lot_statuses


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("proofs")
    parser.add_argument("history")
    parser.add_argument("output")
    args = parser.parse_args()
    statuses = derive_lot_statuses(Path(args.proofs), Path(args.history))
    Path(args.output).write_text(
        json.dumps(statuses, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
