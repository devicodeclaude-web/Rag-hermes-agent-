"""Rendre une réponse citée à partir d'une évidence DÉJÀ autorisée.

Module neutre : il ne récupère rien, n'autorise rien, ne calibre rien et
n'audite rien. Il vit en dehors de `service.py` pour qu'une voie G1 puisse
produire une réponse citée sans dépendre du service, et réciproquement, sans
import circulaire quand le câblage inverse arrivera (`g1_audited_candidates`
importait `service`, et `service` devra plus tard nommer les types G1).

Règle permanente : une fenêtre de candidats VIDE n'est pas une abstention. Elle
remonte ici en `GenerationError`, pas en liste vide ni en réponse d'abstention.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re

from .acl import Chunk
from .generator import ABSTENTION_ANSWER, GenerationError

__all__ = [
    "ABSTENTION_ANSWER",
    "AnswerResponse",
    "AnswerTrace",
    "Citation",
    "answer_from_evidence",
]

_CITATION_MARKER_RE = re.compile(r"\[S(\d+)\]")


@dataclass(frozen=True)
class Citation:
    document_id: str
    chunk_id: str
    source_uri: str
    quote: str


@dataclass(frozen=True)
class AnswerResponse:
    answer: str
    abstained: bool
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class AnswerTrace:
    """Internal evaluation trace from the production answer path."""

    response: AnswerResponse
    retrieved_chunks: tuple[Chunk, ...]
    cited_chunks: tuple[Chunk, ...]


def answer_from_evidence(
    question: str,
    evidence: tuple[Chunk, ...],
    *,
    generator: Callable[[str, tuple[Chunk, ...]], str] | None,
    strict_citations: bool = True,
) -> AnswerTrace:
    """Render ONLY the supplied evidence, in the order supplied.

    The caller owns authorization, scoring and auditing: this function trusts
    `evidence` completely and must therefore never be handed candidates that a
    canonical ACL/provenance barrier has not already accepted.

    `strict_citations=True` (the default, i.e. the safe mode) REFUSES an answer
    carrying a `[Sn]` marker outside the window instead of silently dropping it:
    a published answer whose text shows an unresolved marker misleads a reader
    and inflates structural-citation metrics computed on resolved citations
    only. `RagService` opts out explicitly for backward compatibility.

    Citations are materialised AFTER the generator returns, from the very Chunk
    objects it received: a hostile generator can rewrite a quote via
    `object.__setattr__` (frozen dataclasses are not immune). Rebinding the
    evidence to a trusted manifest after generation is the CALLER's job; the
    audited G1 window does exactly that.
    """
    if not evidence:
        # SERVER-side invariant breach, not a bad client request: GenerationError
        # maps to HTTP 502. A bare ValueError would surface as 400 and blame the
        # caller for an empty pipeline window.
        raise GenerationError("no verified evidence in candidate window")
    # `is None`, NOT falsiness: a CALLABLE generator whose `__bool__` returns
    # False (or whose `__len__` returns 0) would otherwise silently fall back to
    # the extractive branch, publishing a passage while the caller believes the
    # configured generator ran.
    if generator is None:
        # Extractive default: single best chunk with its citation.
        top = evidence[0]
        response = AnswerResponse(
            answer=top.text,
            abstained=False,
            citations=(
                Citation(
                    document_id=top.document_id,
                    chunk_id=top.chunk_id,
                    source_uri=top.source_uri,
                    quote=top.text,
                ),
            ),
        )
        return AnswerTrace(response, tuple(evidence), (top,))
    answer = generator(question, evidence)
    # Validate the TYPE before any comparison: a str subclass with a lying
    # `__eq__` compared equal to the abstention sentinel, which skipped both the
    # marker guard and the zero-citation guard and published arbitrary text as
    # an abstention. `type(x) is str` also rejects bytes and non-strings.
    if type(answer) is not str:
        raise GenerationError("generated answer must be a plain string")
    if answer == ABSTENTION_ANSWER:
        response = AnswerResponse(answer=answer, abstained=True, citations=())
        return AnswerTrace(response, tuple(evidence), ())
    # Keep only citations the generator actually referenced via [Sn]. The
    # markers are compared as strings against the allowed set, so an
    # attacker-controlled marker with an astronomically long digit run can
    # never trigger an int() conversion here. Preserve first-cited order,
    # deduplicated.
    allowed = {str(position): position - 1 for position in range(1, len(evidence) + 1)}
    cited_indices: list[int] = []
    for marker in _CITATION_MARKER_RE.findall(answer):
        if strict_citations and marker not in allowed:
            raise GenerationError("generated answer contains an invalid citation")
        index = allowed.get(marker)
        if index is not None and index not in cited_indices:
            cited_indices.append(index)
    citations = tuple(
        Citation(
            document_id=evidence[index].document_id,
            chunk_id=evidence[index].chunk_id,
            source_uri=evidence[index].source_uri,
            quote=evidence[index].text,
        )
        for index in cited_indices
    )
    # Fail closed: a non-abstention answer must resolve to at least one
    # citation, regardless of which generator is injected. The bundled
    # generator already enforces this, but we must not trust an arbitrary
    # generator to keep the marker->citation invariant.
    if not citations:
        raise GenerationError(
            "generated answer resolved to zero valid citations"
        )
    response = AnswerResponse(
        answer=answer,
        abstained=False,
        citations=citations,
    )
    cited_chunks = tuple(evidence[index] for index in cited_indices)
    return AnswerTrace(response, tuple(evidence), cited_chunks)
