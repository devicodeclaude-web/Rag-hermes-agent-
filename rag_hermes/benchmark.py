from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .acl import AuthorizationContext
from .evaluation import EvaluationCase, EvaluationReport, evaluate
from .ingestion import Document, chunk_document
from .retrieval import LexicalRetriever


@dataclass(frozen=True)
class BenchmarkQuestion:
    case_id: str
    question: str
    context: AuthorizationContext
    relevant_document_ids: tuple[str, ...]
    should_abstain: bool


def run_lexical_benchmark(
    documents: Iterable[Document],
    questions: Iterable[BenchmarkQuestion],
    *,
    k: int = 10,
    minimum_score: float = 0.5,
) -> tuple[EvaluationReport, list[EvaluationCase]]:
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(document, max_tokens=420, overlap_tokens=40)
    ]
    retriever = LexicalRetriever(chunks)
    cases: list[EvaluationCase] = []

    for question in questions:
        results = [
            result
            for result in retriever.search(
                question.question, context=question.context, limit=k
            )
            if result.score >= minimum_score
        ]
        retrieved_ids = tuple(dict.fromkeys(result.chunk.document_id for result in results))
        relevant_ids = question.relevant_document_ids
        leaked_ids = tuple(
            dict.fromkeys(
                result.chunk.document_id
                for result in results
                if result.chunk.tenant_id not in {question.context.tenant_id, "public"}
            )
        )
        cases.append(
            EvaluationCase(
                case_id=question.case_id,
                relevant_chunk_ids=relevant_ids,
                retrieved_chunk_ids=retrieved_ids,
                cited_chunk_ids=(),
                should_abstain=question.should_abstain,
                did_abstain=not results,
                leaked_chunk_ids=leaked_ids,
            )
        )

    return evaluate(cases, k=k), cases
