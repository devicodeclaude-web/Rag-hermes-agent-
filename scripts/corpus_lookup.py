#!/usr/bin/env python3
"""Helper for the human annotator: find documents and check passages.

Anti-circularity note: use this AFTER you have written a question, to locate the
passage that answers it — not to invent questions from the corpus text.

Usage:
  # 1. Find candidate documents by keyword (searches document_id + content):
  python scripts/corpus_lookup.py find "agent loop"

  # 2. Show a document's id and a slice of its content (to copy a passage):
  python scripts/corpus_lookup.py show "hermes-agent:developer-guide/agent-loop.md" --start 0 --length 800

  # 3. Verify a passage is present verbatim AND unique (what ingestion requires):
  python scripts/corpus_lookup.py check "hermes-agent:developer-guide/agent-loop.md" "the exact passage text"
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.eval_corpus import DEFAULT_CORPUS, find_passage_span, load_documents


def cmd_find(docs, args) -> int:
    needle = args.query.lower()
    hits = []
    for did, doc in docs.items():
        content = str(doc["content"])
        if needle in did.lower() or needle in content.lower():
            pos = content.lower().find(needle)
            snippet = content[max(0, pos - 30): pos + 60].replace("\n", " ") if pos >= 0 else ""
            hits.append((did, len(content), snippet))
    hits.sort()
    for did, length, snippet in hits[: args.limit]:
        print(f"{did}  [{length} chars]")
        if snippet:
            print(f"    …{snippet}…")
    print(f"\n{len(hits)} document(s) matched (showing up to {args.limit}).")
    return 0


def cmd_show(docs, args) -> int:
    if args.document_id not in docs:
        print(f"unknown document_id: {args.document_id}", file=sys.stderr)
        return 1
    content = str(docs[args.document_id]["content"])
    end = args.start + args.length
    print(content[args.start:end])
    print(f"\n--- shown chars [{args.start}:{end}] of {len(content)} ---")
    return 0


def cmd_check(docs, args) -> int:
    try:
        span = find_passage_span(docs, args.document_id, args.passage_text)
    except ValueError as exc:
        print(f"NOT USABLE: {exc}", file=sys.stderr)
        return 1
    print("USABLE verbatim + unique:")
    print(f"  document_id : {span['document_id']}")
    print(f"  start_char  : {span['start_char']}")
    print(f"  end_char    : {span['end_char']}")
    print(f"  sha256      : {span['passage_sha256']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_find = sub.add_parser("find", help="find documents by keyword")
    p_find.add_argument("query")
    p_find.add_argument("--limit", type=int, default=20)

    p_show = sub.add_parser("show", help="print a slice of a document")
    p_show.add_argument("document_id")
    p_show.add_argument("--start", type=int, default=0)
    p_show.add_argument("--length", type=int, default=800)

    p_check = sub.add_parser("check", help="verify a passage is verbatim + unique")
    p_check.add_argument("document_id")
    p_check.add_argument("passage_text")

    args = parser.parse_args()
    docs = load_documents(args.corpus)
    if args.cmd == "find":
        return cmd_find(docs, args)
    if args.cmd == "show":
        return cmd_show(docs, args)
    if args.cmd == "check":
        return cmd_check(docs, args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
