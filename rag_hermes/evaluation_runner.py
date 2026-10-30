from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .acl import AuthorizationContext, Chunk
from .evaluation import EvaluationCase, EvaluationReport, evaluate
from .evaluation_dataset import validate_evaluation_case
from .service import RagService


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by the service, carrying its document offsets.

    Relevance is judged chunking-independently: a retrieved chunk satisfies a
    dataset relevance span when it belongs to the same document AND its
    character interval overlaps the span's interval.
    """

    chunk: Chunk


# answer_fn(question, validated_case) -> (retrieved, cited, abstained)
AnswerFn = Callable[
    [str, Mapping[str, object]],
    tuple[Sequence[RetrievedChunk], Sequence[RetrievedChunk], bool],
]
ContextFn = Callable[[Mapping[str, object]], AuthorizationContext]


def build_service_answer_fn(
    service: RagService,
    context_for_case: ContextFn,
) -> AnswerFn:
    """Adapt RagService's production answer path to the evaluation runner."""

    def answer_fn(
        question: str,
        case: Mapping[str, object],
    ) -> tuple[Sequence[RetrievedChunk], Sequence[RetrievedChunk], bool]:
        context = context_for_case(case)
        if not isinstance(context, AuthorizationContext):
            raise ValueError("context_for_case must return AuthorizationContext")
        trace = service.answer_with_trace(question, context=context)
        return (
            tuple(RetrievedChunk(chunk) for chunk in trace.retrieved_chunks),
            tuple(RetrievedChunk(chunk) for chunk in trace.cited_chunks),
            trace.response.abstained,
        )

    return answer_fn


def _validate_chunk(
    chunk: Chunk,
    documents: Mapping[str, Mapping[str, object]],
) -> None:
    if type(chunk.start_offset) is not int or type(chunk.end_offset) is not int:
        raise ValueError("chunk offsets must be integers")
    if chunk.start_offset < 0 or chunk.end_offset <= chunk.start_offset:
        raise ValueError(f"invalid chunk offsets for {chunk.chunk_id!r}")
    document = documents.get(chunk.document_id)
    if document is not None:
        content = str(document["content"])
        if chunk.end_offset > len(content):
            raise ValueError(
                f"chunk {chunk.chunk_id!r} extends outside canonical document"
            )
        if chunk.text != content[chunk.start_offset : chunk.end_offset]:
            raise ValueError(
                f"chunk {chunk.chunk_id!r} text does not match canonical document"
            )


def _overlaps(chunk: Chunk, document_id: str, start: int, end: int) -> bool:
    if chunk.document_id != document_id:
        return False
    # Half-open intervals [start, end); overlap iff they intersect.
    return chunk.start_offset < end and start < chunk.end_offset


def run_evaluation(
    cases: Sequence[Mapping[str, object]],
    documents: Mapping[str, Mapping[str, object]],
    manifest: Mapping[str, object],
    answer_fn: AnswerFn,
    *,
    k: int,
    authorized_document_ids: set[str] | None = None,
) -> EvaluationReport:
    """Execute each dataset case through answer_fn and score with evaluate().

    Every case is validated against the strict schema BEFORE execution, so a
    stale revision, wrong corpus hash, or chunk-id label aborts the campaign
    instead of silently producing metrics.

    Relevance labels are document spans (not chunk ids). We synthesize a stable
    synthetic "relevant chunk id" per span (document_id + interval) and mark a
    retrieved chunk as matching that span when its offsets overlap; the same
    synthetic id is then fed to evaluate() on both the relevant and retrieved
    sides, keeping evaluate()'s chunk-id contract intact while staying
    chunking-independent at the dataset boundary.
    """
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")

    validated_cases = [
        validate_evaluation_case(raw_case, documents, manifest)
        for raw_case in cases
    ]
    case_ids = [str(case["case_id"]) for case in validated_cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate case_id")

    evaluation_cases: list[EvaluationCase] = []
    for case in validated_cases:
        spans = case["relevance_spans"]
        same_scope_document_ids = {
            document_id
            for document_id, document in documents.items()
            if document.get("visibility") == case["access_scope"]
        }
        case_authorized_document_ids = same_scope_document_ids
        if authorized_document_ids is not None:
            case_authorized_document_ids = (
                same_scope_document_ids.intersection(authorized_document_ids)
            )

        # Assign a stable synthetic label id to each relevance span.
        span_labels: list[tuple[str, str, int, int]] = []
        for index, span in enumerate(spans):
            document_id = str(span["document_id"])
            start = int(span["start_char"])
            end = int(span["end_char"])
            label = f"span:{document_id}#span{index}:{start}-{end}"
            span_labels.append((label, document_id, start, end))

        retrieved, cited, abstained = answer_fn(case["question"], case)
        if type(abstained) is not bool:
            raise ValueError("answer_fn abstained must be a bool")

        # Map retrieved chunks to the span labels they cover (relevance).
        retrieved_labels: list[str] = []
        retrieved_relevance_ids_by_rank: list[tuple[str, ...]] = []
        leaked: set[str] = set()
        retrieved_chunks: list[Chunk] = []
        for item in retrieved:
            chunk = item.chunk
            retrieved_chunks.append(chunk)
            _validate_chunk(chunk, documents)
            if chunk.document_id not in case_authorized_document_ids:
                leaked.add(chunk.chunk_id)
            matched = [
                label
                for (label, document_id, start, end) in span_labels
                if _overlaps(chunk, document_id, start, end)
            ]
            retrieved_relevance_ids_by_rank.append(tuple(matched))
            # A retrieved chunk covering no span gets a disjoint namespaced
            # label, so an attacker-controlled chunk id cannot collide with a
            # relevance label while rank and misses remain observable.
            retrieved_labels.append(
                matched[0] if matched else f"chunk:{chunk.chunk_id}"
            )

        cited_labels: list[str] = []
        for item in cited:
            chunk = item.chunk
            if chunk not in retrieved_chunks:
                raise ValueError("citation was not retrieved")
            _validate_chunk(chunk, documents)
            if chunk.document_id not in case_authorized_document_ids:
                leaked.add(chunk.chunk_id)
            matched = [
                label
                for (label, document_id, start, end) in span_labels
                if _overlaps(chunk, document_id, start, end)
            ]
            cited_labels.append(
                matched[0] if matched else f"chunk:{chunk.chunk_id}"
            )

        evaluation_cases.append(
            EvaluationCase(
                case_id=str(case["case_id"]),
                relevant_chunk_ids=tuple(label for (label, _d, _s, _e) in span_labels),
                retrieved_chunk_ids=tuple(retrieved_labels),
                cited_chunk_ids=tuple(cited_labels),
                should_abstain=case["should_abstain"],
                did_abstain=abstained,
                leaked_chunk_ids=tuple(sorted(leaked)),
                retrieved_relevance_ids_by_rank=tuple(
                    retrieved_relevance_ids_by_rank
                ),
            )
        )

    return evaluate(evaluation_cases, k=k)
