from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Mapping

_ALLOWED_SCOPES = {"public", "private"}
_ALLOWED_REFERENCE_STATUS = {"pending", "validated", "arbitrated"}
_ALLOWED_PROVENANCE = {
    "human_task_without_corpus_view",
    "anonymized_real_user_question",
}
# Language is an explicit experimental condition, never an implicit property.
_ALLOWED_LANGUAGE = {"en", "fr"}
# Track is the language condition of the retrieval experiment.
#   en2en : English question over the English public corpus (BM25 is a valid baseline).
#   fr2en : French question over the same English corpus (cross-lingual; BM25 not comparable).
_ALLOWED_TRACK = {"en2en", "fr2en"}
# track -> the language its question must be written in.
_TRACK_LANGUAGE = {"en2en": "en", "fr2en": "fr"}


def validate_evaluation_case(
    case: Mapping[str, Any],
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate chunking-independent relevance labels against canonical documents.

    ``manifest`` pins the corpus identity and MUST provide:
      - ``source_revision``     : the exact source Git revision of the corpus;
      - ``corpus_manifest_sha`` : the SHA-256 of the canonical corpus file.
    Every case must echo both, and a case is refused if either diverges from the
    pinned manifest. A stale revision or a wrong corpus hash cannot silently pass.
    """
    pinned_revision = str(manifest.get("source_revision", ""))
    pinned_sha = str(manifest.get("corpus_manifest_sha", ""))
    if not pinned_revision or not pinned_sha:
        raise ValueError("manifest must pin both source_revision and corpus_manifest_sha")

    if "relevant_chunk_ids" in case:
        raise ValueError("chunk identifiers cannot be primary relevance labels")

    required = {
        "case_id",
        "question",
        "language",
        "track",
        "category",
        "access_scope",
        "question_provenance",
        "should_abstain",
        "unanswerable_reason",
        "reference_status",
        "relevance_spans",
        "source_revision",
        "corpus_manifest_sha",
    }
    missing = sorted(required - set(case))
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")

    # Corpus identity: refuse a case pinned to a different revision or corpus hash.
    if str(case["source_revision"]) != pinned_revision:
        raise ValueError(
            f"source_revision {case['source_revision']!r} does not match pinned manifest "
            f"revision {pinned_revision!r}"
        )
    if str(case["corpus_manifest_sha"]) != pinned_sha:
        raise ValueError(
            "corpus_manifest_sha does not match pinned manifest corpus hash"
        )

    language = str(case["language"])
    if language not in _ALLOWED_LANGUAGE:
        raise ValueError(f"invalid language: {language}")
    track = str(case["track"])
    if track not in _ALLOWED_TRACK:
        raise ValueError(f"invalid track: {track}")
    if _TRACK_LANGUAGE[track] != language:
        raise ValueError(
            f"track {track!r} requires language {_TRACK_LANGUAGE[track]!r}, got {language!r}"
        )

    scope = str(case["access_scope"])
    if scope not in _ALLOWED_SCOPES:
        raise ValueError(f"invalid access_scope: {scope}")
    if case["question_provenance"] not in _ALLOWED_PROVENANCE:
        raise ValueError("question provenance does not establish corpus-independent authoring")
    if case["reference_status"] not in _ALLOWED_REFERENCE_STATUS:
        raise ValueError("invalid reference_status")

    spans = case["relevance_spans"]
    if not isinstance(spans, list):
        raise ValueError("relevance_spans must be a list")
    should_abstain = bool(case["should_abstain"])
    if should_abstain:
        if spans:
            raise ValueError("an abstention case cannot contain relevance spans")
        if not case["unanswerable_reason"]:
            raise ValueError("unanswerable_reason is required for an abstention case")
    else:
        if not spans:
            raise ValueError("an answerable case requires at least one relevance span")
        if case["unanswerable_reason"] is not None:
            raise ValueError("answerable cases must set unanswerable_reason to null")

    for index, span in enumerate(spans):
        if "chunk_id" in span or "relevant_chunk_ids" in span:
            raise ValueError("chunk identifiers cannot appear in relevance spans")
        document_id = str(span.get("document_id", ""))
        if document_id not in documents:
            raise ValueError(f"unknown document_id in span {index}: {document_id}")
        document = documents[document_id]
        if document.get("visibility") != scope:
            raise ValueError(
                f"document visibility {document.get('visibility')!r} does not match access_scope {scope!r}"
            )
        content = str(document["content"])
        start = int(span.get("start_char", -1))
        end = int(span.get("end_char", -1))
        if start < 0 or end <= start or end > len(content):
            raise ValueError(f"invalid character interval in span {index}")
        passage = content[start:end]
        expected_hash = hashlib.sha256(passage.encode("utf-8")).hexdigest()
        if span.get("passage_sha256") != expected_hash:
            raise ValueError(f"passage_sha256 does not match canonical document in span {index}")
        if span.get("relevance_grade") not in {1, 2}:
            raise ValueError(f"relevance_grade must be 1 or 2 in span {index}")

    return deepcopy(dict(case))
