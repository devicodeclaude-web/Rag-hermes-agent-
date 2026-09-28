#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.qdrant_provision import provision_collection
from rag_hermes.qdrant_rest import QdrantRestClient


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crée ou complète idempotemment la collection Qdrant du RAG Hermes."
        )
    )
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="hermes_chunks_v1")
    parser.add_argument("--vector-size", type=int, default=1024)
    parser.add_argument("--index-spec", default="qdrant/payload-indexes.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    specification = json.loads(Path(args.index_spec).read_text(encoding="utf-8"))
    client = QdrantRestClient(args.url, timeout=120)
    report = provision_collection(
        client=client,
        collection=args.collection,
        vector_size=args.vector_size,
        specification=specification,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
