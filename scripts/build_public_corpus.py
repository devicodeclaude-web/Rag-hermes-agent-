#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from rag_hermes.dataset import documents_from_markdown


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    documents = documents_from_markdown(args.docs_root, commit=args.commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for document in documents:
            handle.write(json.dumps(asdict(document), ensure_ascii=False) + "\n")
    print(json.dumps({"documents": len(documents), "commit": args.commit, "output": str(args.output)}))


if __name__ == "__main__":
    main()
