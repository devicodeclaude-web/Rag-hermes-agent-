from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "data/generated/hermes_public_documents.jsonl"

# git+https://github.com/NousResearch/hermes-agent.git@<rev>#<path>
_REVISION_RE = re.compile(r"@([0-9a-f]{7,40})#")


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def load_documents(corpus_path: Path = DEFAULT_CORPUS) -> dict[str, dict[str, Any]]:
    """Load canonical documents indexed by document_id."""
    documents: dict[str, dict[str, Any]] = {}
    for line in corpus_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        documents[doc["document_id"]] = doc
    if not documents:
        raise ValueError(f"empty corpus: {corpus_path}")
    return documents


def _extract_revision(documents: dict[str, dict[str, Any]]) -> str:
    """Extract the single source revision pinned across every source_uri."""
    revisions: set[str] = set()
    for doc in documents.values():
        match = _REVISION_RE.search(str(doc.get("source_uri", "")))
        if match:
            revisions.add(match.group(1))
    if len(revisions) != 1:
        raise ValueError(f"corpus does not pin exactly one source revision: {sorted(revisions)}")
    return next(iter(revisions))


def corpus_manifest(corpus_path: Path = DEFAULT_CORPUS) -> dict[str, str]:
    """Return the pinned corpus identity: source_revision + corpus_manifest_sha.

    These are the exact values the evaluation-dataset validator pins each case to.
    """
    documents = load_documents(corpus_path)
    return {
        "source_revision": _extract_revision(documents),
        "corpus_manifest_sha": sha256_of_file(corpus_path),
    }


def find_passage_span(
    documents: dict[str, dict[str, Any]],
    document_id: str,
    passage_text: str,
) -> dict[str, Any]:
    """Locate a passage by its exact text and return a chunking-independent span.

    The annotator supplies the passage text (copied from the document they judged
    relevant), never raw offsets. This computes start/end char and the SHA-256 so
    the label stays independent of any chunking scheme.
    """
    if document_id not in documents:
        raise ValueError(f"unknown document_id: {document_id}")
    content = str(documents[document_id]["content"])
    start = content.find(passage_text)
    if start < 0:
        raise ValueError("passage_text not found verbatim in the canonical document")
    if content.find(passage_text, start + 1) != -1:
        raise ValueError("passage_text is ambiguous (appears more than once); extend it")
    end = start + len(passage_text)
    return {
        "document_id": document_id,
        "start_char": start,
        "end_char": end,
        "passage_sha256": hashlib.sha256(passage_text.encode("utf-8")).hexdigest(),
    }
