from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Callable, Mapping, Protocol, Sequence, cast

from .acl import AuthorizationContext, Chunk
from .acl_authority import AclPolicy, CanonicalAclAuthority
from .evaluation import (
    EvaluationCase,
    EvaluationReport,
    TechnicalFailure,
    evaluate,
)
from .evaluation_dataset import validate_evaluation_case
from .generator import GenerationError
from .index_integrity import AuditedIndexSession
from .retrieval import CanonicalAclError
from .service import AnswerTrace


class AnswerPath(Protocol):
    def answer_with_trace(
        self, question: str, *, context: AuthorizationContext,
    ) -> AnswerTrace: ...


class CaseExecutionError(Exception):
    """A case could not be executed, with the terminal status it must receive.

    This is the ONLY way an answer_fn tells the runner "record this case as a
    technical failure". Broad exception classes are deliberately NOT caught: a
    harness bug, a typo or a transport crash relabelled as `backend_error`
    would be a false audit finding in a component whose whole purpose is to
    produce evidence. Callers that know a service's exception vocabulary
    translate it here explicitly (see `build_service_answer_fn`); anything
    unrecognised aborts the campaign instead of being classified.

    The message is kept for the operator but is NEVER published in the report:
    a transport error's text routinely embeds a URL, a response body or
    credentials, and the report is a committed artefact.
    """

    def __init__(self, terminal_status: TechnicalFailure, detail: str = "") -> None:
        if terminal_status not in {"acl_error", "backend_error"}:
            raise ValueError("terminal_status must be acl_error or backend_error")
        super().__init__(detail or terminal_status)
        self.terminal_status: TechnicalFailure = terminal_status


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
# Audited campaigns receive the SAME resolved context used to score ACL leaks.
AuditedAnswerFn = Callable[
    [str, Mapping[str, object], AuthorizationContext],
    tuple[Sequence[RetrievedChunk], Sequence[RetrievedChunk], bool],
]


def _answer_via_service(
    service: AnswerPath,
    question: str,
    context: AuthorizationContext,
) -> tuple[Sequence[RetrievedChunk], Sequence[RetrievedChunk], bool]:
    """Call the service, translating ITS exception vocabulary -- and only that.

    `CanonicalAclError` is emitted by the canonical bridge on fail-closed
    decisions. Other `PermissionError` exceptions propagate and abort the
    campaign: a storage permission failure is not evidence of an ACL refusal.
    `GenerationError` indicates a generator/backend failure. Both become a
    signalled `CaseExecutionError` so the runner can record a terminal status.
    Every other exception propagates untouched and aborts the campaign: a
    harness bug or a transport crash must not be published as an ACL finding.

    The cause is attached (`from exc`) so the operator keeps the detail, but its
    text is NOT interpolated into the signalled message -- a transport error
    routinely embeds a URL, a response body or credentials, and the campaign
    report is a committed artefact.
    """
    try:
        trace = service.answer_with_trace(question, context=context)
    except CanonicalAclError as exc:
        raise CaseExecutionError("acl_error", "ACL barrier failed closed") from exc
    except GenerationError as exc:
        raise CaseExecutionError("backend_error", "generation backend failed") from exc
    return (
        tuple(RetrievedChunk(chunk) for chunk in trace.retrieved_chunks),
        tuple(RetrievedChunk(chunk) for chunk in trace.cited_chunks),
        trace.response.abstained,
    )


def build_service_answer_fn(
    service: AnswerPath,
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
        return _answer_via_service(service, question, context)

    return answer_fn


def build_contextual_service_answer_fn(service: AnswerPath) -> AuditedAnswerFn:
    """Use the audited campaign's resolved context on the service answer path."""
    def answer_fn(question: str, case: Mapping[str, object], context: AuthorizationContext):
        return _answer_via_service(service, question, context)
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
    answer_fn: AnswerFn | AuditedAnswerFn,
    *,
    k: int,
    authorized_document_ids: set[str] | None = None,
    context_for_case: ContextFn | None = None,
    authority: CanonicalAclAuthority | None = None,
) -> EvaluationReport:
    """Execute each dataset case through answer_fn and score with evaluate().

    Every case is validated against the strict schema BEFORE execution, so a
    stale revision, wrong corpus hash, or chunk-id label aborts the campaign
    instead of silently producing metrics. Without both `context_for_case` and
    `authority`, `security_gate_passed` is only a scope/allowlist check, not an
    owner, group, tenant or clearance check; use the audited wrapper for the
    context-bound path. Even there, a supplied answer_fn is not proven to use
    the same context or the audited index.

    Relevance labels are document spans (not chunk ids). We synthesize a stable
    synthetic "relevant chunk id" per span (document_id + interval) and mark a
    retrieved chunk as matching that span when its offsets overlap; the same
    synthetic id is then fed to evaluate() on both the relevant and retrieved
    sides, keeping evaluate()'s chunk-id contract intact while staying
    chunking-independent at the dataset boundary.
    """
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    if (context_for_case is None) != (authority is None):
        raise ValueError("context_for_case and authority must be supplied together")

    validated_cases = [
        validate_evaluation_case(raw_case, documents, manifest)
        for raw_case in cases
    ]
    case_ids = [str(case["case_id"]) for case in validated_cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate case_id")
    if authority is not None:
        # The span corpus and the ACL registry are two trusted inputs. A clean
        # Qdrant snapshot does not reconcile them; fail before answering if
        # either source disagrees or an ACL policy is missing.
        for document_id, document in documents.items():
            policy = authority.policy_for(document_id)
            if type(policy) is not AclPolicy:
                raise ValueError("canonical document has no exact ACL policy")
            if type(policy.tenant_id) is not str or not policy.tenant_id:
                raise ValueError("canonical ACL policy tenant must be a non-empty string")
            if type(policy.visibility) is not str or policy.visibility not in {"public", "private"}:
                raise ValueError("canonical ACL policy visibility is invalid")
            if type(policy.owner_id) is not str:
                raise ValueError("canonical ACL policy owner must be a string")
            if type(policy.allowed_groups) is not tuple or any(
                type(group) is not str for group in policy.allowed_groups
            ):
                raise ValueError("canonical ACL policy groups must be strings")
            if type(policy.allowed_users) is not tuple or any(
                type(user) is not str for user in policy.allowed_users
            ):
                raise ValueError("canonical ACL policy users must be strings")
            if type(policy.classification) is not int or policy.classification < 0:
                raise ValueError("canonical ACL policy classification is invalid")
            if type(policy.acl_version) is not int or policy.acl_version < 1:
                raise ValueError("canonical ACL policy version is invalid")
            if document.get("visibility") != policy.visibility:
                raise ValueError("canonical document visibility disagrees with ACL policy")
            if "tenant_id" in document and (
                type(document["tenant_id"]) is not str
                or document["tenant_id"] != policy.tenant_id
            ):
                raise ValueError("canonical document tenant disagrees with ACL policy")

    evaluation_cases: list[EvaluationCase] = []
    for case in validated_cases:
        context = context_for_case(case) if context_for_case is not None else None
        if context_for_case is not None:
            if type(context) is not AuthorizationContext:
                raise ValueError("context_for_case must return AuthorizationContext")
            if type(context.tenant_id) is not str or not context.tenant_id:
                raise ValueError("authorization context tenant must be a string")
            if type(context.user_id) is not str or not context.user_id:
                raise ValueError("authorization context user must be a string")
            if type(context.groups) is not tuple or any(
                type(group) is not str for group in context.groups
            ):
                raise ValueError("authorization context groups must be strings")
            if type(context.clearance) is not int or context.clearance < 0:
                raise ValueError("authorization context clearance must be a non-negative integer")
        spans = case["relevance_spans"]
        if authority is not None:
            assert context is not None
            for span in spans:
                policy = authority.policy_for(span["document_id"])
                if policy is None or not policy.allows(context):
                    raise ValueError("reference document is not authorized for case context")
        scope_eligible_document_ids = {
            document_id
            for document_id, document in documents.items()
            if document.get("visibility") == case["access_scope"]
            or (authority is not None and case["access_scope"] == "private"
                and document.get("visibility") == "public")
        }
        case_authorized_document_ids = scope_eligible_document_ids
        if authorized_document_ids is not None:
            case_authorized_document_ids = (
                scope_eligible_document_ids.intersection(authorized_document_ids)
            )

        def is_authorized(chunk: Chunk) -> bool:
            if chunk.document_id not in case_authorized_document_ids:
                return False
            if authority is None:
                return True  # Legacy scorer: scope/explicit allowlist only.
            assert context is not None
            policy = authority.policy_for(chunk.document_id)
            if policy is None:
                return False
            indexed_policy = AclPolicy(
                tenant_id=chunk.tenant_id,
                visibility=chunk.visibility,
                owner_id=chunk.owner_id,
                allowed_groups=chunk.allowed_groups,
                allowed_users=chunk.allowed_users,
                classification=chunk.classification,
                acl_version=chunk.acl_version,
            )
            if json.dumps(asdict(policy), sort_keys=True, allow_nan=False) != json.dumps(
                asdict(indexed_policy), sort_keys=True, allow_nan=False
            ):
                return False
            return authority.authorize(chunk.document_id, chunk.acl_version, context)[0]

        # Assign a stable synthetic label id to each relevance span.
        span_labels: list[tuple[str, str, int, int]] = []
        for index, span in enumerate(spans):
            document_id = str(span["document_id"])
            start = int(span["start_char"])
            end = int(span["end_char"])
            label = f"span:{document_id}#span{index}:{start}-{end}"
            span_labels.append((label, document_id, start, end))

        try:
            if authority is None:
                retrieved, cited, abstained = cast(AnswerFn, answer_fn)(
                    case["question"], case
                )
            else:
                assert context is not None
                retrieved, cited, abstained = cast(AuditedAnswerFn, answer_fn)(
                    case["question"], case, context
                )
        except CaseExecutionError as failure:
            # Record the signalled terminal status and move on. The case keeps
            # its relevance labels with ZERO retrievals, so a crash counts as a
            # retrieval miss rather than vanishing from recall -- the same
            # anti-inflation direction as the abstention denominators. Error
            # counts are published separately so a reader can recompute the
            # alternative. The exception message is deliberately dropped: it can
            # embed a URL, a response body or credentials, and the report is a
            # committed artefact.
            evaluation_cases.append(
                EvaluationCase(
                    case_id=str(case["case_id"]),
                    relevant_chunk_ids=tuple(
                        label for (label, _d, _s, _e) in span_labels
                    ),
                    retrieved_chunk_ids=(),
                    cited_chunk_ids=(),
                    should_abstain=case["should_abstain"],
                    did_abstain=False,
                    leaked_chunk_ids=(),
                    technical_failure=failure.terminal_status,
                    retrieved_relevance_ids_by_rank=(),
                )
            )
            continue
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
            if not is_authorized(chunk):
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
            if not is_authorized(chunk):
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


def run_audited_evaluation(
    session: AuditedIndexSession,
    cases: Sequence[Mapping[str, object]],
    documents: Mapping[str, Mapping[str, object]],
    manifest: Mapping[str, object],
    answer_fn: AuditedAnswerFn,
    *,
    k: int,
    context_for_case: ContextFn,
    authority: CanonicalAclAuthority,
    authorized_document_ids: set[str] | None = None,
) -> EvaluationReport:
    """Score a campaign only if the index audit passed before AND after it.

    This makes the audit a precondition for CALLERS OF THIS FUNCTION: the opening
    audit runs before the first question, so a failing index answers no case at
    all, and the closing audit must pass before any report is returned. What this
    establishes is bounded: **the session's index** matched the canonical manifest
    at both ends of the run. `answer_fn` is an arbitrary callable, so this
    function cannot verify that the questions were actually served by the audited
    collection — binding the two remains the operator's job. The audited path
    requires a canonical ACL authority and a context for each case before its
    `security_gate_passed` score can be interpreted as an ACL leak check. The
    resolved context is handed to the three-argument `answer_fn` (the supplied
    service adapter uses it directly), but an arbitrary callable can ignore it.
    The score checks ACL, not chunk provenance/version/URI or search completeness.

    It does not make the audit a property of the system: a campaign driven
    through `run_evaluation` directly, or any query issued outside this call,
    remains unaudited. The session's own limits still apply — it prevents no
    write, and a divergence reverted before the closing audit, or one touching
    only vectors, stays invisible.
    """
    if type(session) is not AuditedIndexSession:
        raise TypeError("session must be an exact AuditedIndexSession")
    if type(authority) is not CanonicalAclAuthority:
        raise TypeError("authority must be an exact CanonicalAclAuthority")
    if not callable(context_for_case):
        raise TypeError("context_for_case must be callable")
    session.open()
    try:
        report = run_evaluation(
            cases,
            documents,
            manifest,
            answer_fn,
            k=k,
            authorized_document_ids=authorized_document_ids,
            context_for_case=context_for_case,
            authority=authority,
        )
    except BaseException:
        # Burn the session WITHOUT auditing: an aborted campaign claims nothing
        # about the index, and a closing audit here would both cost a full scroll
        # on an interrupt path and discard its own divergence error while the
        # scoring error propagates.
        session.invalidate()
        raise
    session.close()
    return report
