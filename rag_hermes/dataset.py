from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, TypeVar

from .acl import AuthorizationContext
from .benchmark import BenchmarkQuestion
from .ingestion import Document


def documents_from_markdown(root: str | Path, *, commit: str) -> list[Document]:
    base = Path(root)
    documents: list[Document] = []
    paths = sorted({*base.rglob("*.md"), *base.rglob("*.mdx")})
    for path in paths:
        relative = path.relative_to(base).as_posix()
        documents.append(
            Document(
                document_id=f"hermes-agent:{relative}",
                content=path.read_text(encoding="utf-8"),
                tenant_id="public",
                visibility="public",
                owner_id="nousresearch",
                allowed_groups=(),
                allowed_users=(),
                classification=0,
                doc_version=1,
                source_uri=(
                    "git+https://github.com/NousResearch/hermes-agent.git@"
                    f"{commit}#website/docs/{relative}"
                ),
            )
        )
    return documents

T = TypeVar("T")


def _load_jsonl_payload(
    payload: bytes, factory: Callable[[dict[str, Any]], T], *, source: str
) -> list[T]:
    records: list[T] = []
    for line_number, line in enumerate(payload.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            records.append(factory(value))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid JSONL record at {source}:{line_number}: {exc}") from exc
    return records


def _load_jsonl(path: str | Path, factory: Callable[[dict[str, Any]], T]) -> list[T]:
    source = str(path)
    return _load_jsonl_payload(Path(path).read_bytes(), factory, source=source)


def _build_document(value: dict[str, Any]) -> Document:
    return Document(
        document_id=value["document_id"],
        content=value["content"],
        tenant_id=value["tenant_id"],
        visibility=value["visibility"],
        owner_id=value["owner_id"],
        allowed_groups=tuple(value["allowed_groups"]),
        allowed_users=tuple(value["allowed_users"]),
        classification=int(value["classification"]),
        doc_version=int(value["doc_version"]),
        source_uri=value["source_uri"],
        acl_version=int(value.get("acl_version", 1)),
    )


def load_documents_payload(payload: bytes) -> list[Document]:
    return _load_jsonl_payload(payload, _build_document, source="<snapshot>")


def load_documents(path: str | Path) -> list[Document]:
    return _load_jsonl(path, _build_document)


def load_questions(path: str | Path) -> list[BenchmarkQuestion]:
    def build(value: dict[str, Any]) -> BenchmarkQuestion:
        context = AuthorizationContext(
            tenant_id=value["tenant_id"],
            user_id=value["user_id"],
            groups=tuple(value["groups"]),
            clearance=int(value["clearance"]),
        )
        return BenchmarkQuestion(
            case_id=value["case_id"],
            question=value["question"],
            context=context,
            relevant_document_ids=tuple(value["relevant_document_ids"]),
            should_abstain=bool(value["should_abstain"]),
        )

    return _load_jsonl(path, build)
