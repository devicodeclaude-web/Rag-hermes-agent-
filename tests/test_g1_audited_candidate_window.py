"""Fenêtre G1 auditée : candidats seuls, et voie pilote de réponse citée."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rag_hermes.acl import AuthorizationContext
from rag_hermes.index_integrity import AuditedIndexSessionError, verify_index_snapshot
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_preflight import REQUIRED_PAYLOAD_INDEXES
from rag_hermes.qdrant_store import chunk_to_point


class FakeAuditClient:
    def __init__(self, points, events):
        self.points = points
        self.events = events
    def scroll_page(self, collection, *, limit, offset=None):
        self.events.append(("audit", collection, offset))
        return self.points, None


class FakeQueryClient:
    def __init__(self, points, events):
        self.points = points
        self.events = events
        self.fail = False
        self.schema_ready = True
    def get_collection(self, collection):
        self.events.append(("schema", collection))
        return {
            "config": {"params": {
                "vectors": {"dense": {"size": 2, "distance": "Cosine"}},
                "sparse_vectors": {"sparse": {}} if self.schema_ready else {},
            }},
            "payload_schema": {
                field: {"data_type": required.data_type,
                        "params": {"is_tenant": required.is_tenant}}
                for field, required in REQUIRED_PAYLOAD_INDEXES.items()
            },
        }
    def query(self, collection, vector, *, query_filter, limit):
        self.events.append(("dense", collection, limit))
        if self.fail:
            raise RuntimeError("query unavailable")
        return [{**point, "score": 0.9} for point in self.points][:limit]
    def query_sparse(self, collection, weights, *, context, limit):
        self.events.append(("sparse", collection, limit))
        return []


class FakeTokenizer:
    def __call__(self, query, passage, **kwargs):
        return {"input_ids": [1, 2]}


class FakeReranker:
    def __init__(self, events, on_score=None):
        self.events, self.on_score = events, on_score
    def compute_score(self, pairs, **kwargs):
        self.events.append(("rerank", len(pairs), kwargs["max_length"]))
        if self.on_score is not None:
            self.on_score()
        return [0.6 for _ in pairs]


class AuditedG1CandidateWindowTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "documents.jsonl"
        self.document = Document(
            document_id="guide", content="Installez Hermes avec pipx.",
            tenant_id="alpha", visibility="private", owner_id="alice",
            allowed_groups=(), allowed_users=(), classification=1,
            doc_version=1, source_uri="local://guide",
        )
        self.path.write_text(json.dumps(asdict(self.document)) + "\n", encoding="utf-8")
        self.source_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.context = AuthorizationContext("alpha", "alice", (), 1)
        self.chunks = chunk_document(self.document)
        self.points = [chunk_to_point(chunk, [1.0, 0.0]) for chunk in self.chunks]
        self.manifest_sha = verify_index_snapshot(self.chunks, self.points).payload_sha256
        self.events = []
        self.audit = FakeAuditClient(self.points, self.events)
        self.query = FakeQueryClient(self.points, self.events)
        self.model = FakeReranker(self.events)
        self.urls = []

    def reset_document(self, document, context):
        self.document, self.context = document, context
        self.path.write_text(json.dumps(asdict(document)) + "\n", encoding="utf-8")
        self.source_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.chunks = chunk_document(document)
        self.points = [chunk_to_point(chunk, [1.0, 0.0]) for chunk in self.chunks]
        self.manifest_sha = verify_index_snapshot(self.chunks, self.points).payload_sha256
        self.audit.points = self.points
        self.query.points = self.points

    def run_window(self, **overrides):
        from rag_hermes.g1_audited_candidates import run_audited_g1_candidate_window
        def make_audit(url, *, api_key=""):
            self.urls.append(("audit", url, api_key))
            return self.audit
        def make_query(url, *, api_key=""):
            self.urls.append(("query", url, api_key))
            return self.query
        parameters = dict(
            base_url="http://localhost:6333", collection="audited_chunks",
            source_path=self.path, expected_source_sha256=self.source_sha,
            expected_manifest_sha256=self.manifest_sha,
            chunker=chunk_document,
            embed_hybrid=lambda question: ([1.0, 0.0], {"7": 0.5}),
            reranker=self.model, tokenizer=FakeTokenizer(),
            question="comment installer ?", context=self.context,
        )
        parameters.update(overrides)
        with patch("rag_hermes.g1_audited_candidates.QdrantAuditClient", side_effect=make_audit), patch(
            "rag_hermes.g1_audited_candidates.QdrantRestClient", side_effect=make_query
        ):
            return run_audited_g1_candidate_window(**parameters)

    def test_both_audits_bracket_hybrid_query_and_reranking_on_one_collection(self):
        window = self.run_window()
        self.assertEqual([item.chunk.document_id for item in window.candidates], ["guide"])
        self.assertEqual(window.opening.point_count, 1)
        self.assertEqual(window.closing.point_count, 1)
        self.assertEqual(self.urls, [
            ("audit", "http://localhost:6333", ""),
            ("query", "http://localhost:6333", ""),
        ])
        self.assertEqual(self.events, [
            ("schema", "audited_chunks"),
            ("audit", "audited_chunks", None),
            ("dense", "audited_chunks", 40),
            ("sparse", "audited_chunks", 40),
            ("rerank", 1, 512),
            ("audit", "audited_chunks", None),
        ])
        self.assertFalse(hasattr(window, "abstained"))
        self.assertFalse(hasattr(window, "answer"))

    def test_global_public_document_is_allowed_for_private_tenant_caller(self):
        self.reset_document(
            replace(self.document, tenant_id="public", visibility="public",
                    owner_id="system", classification=0),
            self.context,
        )
        window = self.run_window()
        self.assertEqual([item.chunk.document_id for item in window.candidates], ["guide"])
        self.assertEqual([event[0] for event in self.events][-1], "audit")

    def test_group_permission_is_allowed_for_non_owner(self):
        self.reset_document(
            replace(self.document, owner_id="bob", allowed_groups=("support",)),
            AuthorizationContext("alpha", "alice", ("support",), 1),
        )
        window = self.run_window()
        self.assertEqual([item.chunk.document_id for item in window.candidates], ["guide"])
        self.assertEqual([event[0] for event in self.events][-1], "audit")

    def test_allowed_users_permission_is_allowed_for_non_owner(self):
        self.reset_document(
            replace(self.document, owner_id="bob", allowed_users=("alice",)),
            self.context,
        )
        window = self.run_window()
        self.assertEqual([item.chunk.document_id for item in window.candidates], ["guide"])
        self.assertEqual([event[0] for event in self.events][-1], "audit")

    def test_missing_sparse_schema_fails_before_any_scroll_or_query(self):
        from rag_hermes.qdrant_preflight import QdrantPreflightError
        self.query.schema_ready = False
        with self.assertRaises(QdrantPreflightError):
            self.run_window()
        self.assertEqual(self.events, [("schema", "audited_chunks")])

    def test_index_divergence_at_open_blocks_retrieval_and_reranking(self):
        self.audit.points = [{**self.points[0], "payload": {
            **self.points[0]["payload"], "owner_id": "bob",
        }}]
        with self.assertRaisesRegex(AuditedIndexSessionError, "opening audit failed"):
            self.run_window()
        self.assertEqual([event[0] for event in self.events], ["schema", "audit"])

    def test_bad_manifest_pin_refuses_before_any_query_or_scroll(self):
        with self.assertRaises(AuditedIndexSessionError):
            self.run_window(expected_manifest_sha256="0" * 64)
        self.assertEqual(self.events, [("schema", "audited_chunks")])

    def test_bad_source_digest_refuses_before_any_query_or_scroll(self):
        with self.assertRaises(ValueError):
            self.run_window(expected_source_sha256="0" * 64)
        self.assertEqual(self.events, [])

    def test_query_hit_not_in_audited_manifest_fails_before_model(self):
        # Même document/ACL/texte mais point et chunk_id INVENTÉS par query.
        forged = replace(self.chunks[0], chunk_id="forged-chunk-id")
        self.query.points = [chunk_to_point(forged, [1.0, 0.0])]
        with self.assertRaisesRegex(PermissionError, "audited manifest"):
            self.run_window()
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse",
        ])

    def test_query_hit_with_same_id_but_forged_payload_fails_before_model(self):
        forged = replace(self.chunks[0], token_count=self.chunks[0].token_count + 1)
        self.query.points = [chunk_to_point(forged, [1.0, 0.0])]
        self.assertEqual(self.query.points[0]["id"], self.points[0]["id"])
        with self.assertRaisesRegex(PermissionError, "audited manifest"):
            self.run_window()
        self.assertNotIn("rerank", [event[0] for event in self.events])

    def test_changed_index_at_close_discards_reranked_window(self):
        def tamper():
            self.audit.points = [{**self.points[0], "payload": {
                **self.points[0]["payload"], "owner_id": "bob",
            }}]
        self.model.on_score = tamper
        with self.assertRaisesRegex(AuditedIndexSessionError, "closing audit failed"):
            self.run_window()
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "rerank", "audit",
        ])

    def test_query_error_aborts_without_a_closing_audit(self):
        self.query.fail = True
        with self.assertRaisesRegex(RuntimeError, "query unavailable"):
            self.run_window()
        self.assertEqual([event[0] for event in self.events], ["schema", "audit", "dense"])

    def test_empty_window_still_audits_both_sides_without_calling_model(self):
        self.query.points = []
        window = self.run_window()
        self.assertEqual(window.candidates, ())
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "audit",
        ])

    def run_answer(self, generator, **overrides):
        from rag_hermes.g1_audited_candidates import run_audited_g1_answer
        parameters = dict(
            base_url="http://localhost:6333", collection="audited_chunks",
            source_path=self.path, expected_source_sha256=self.source_sha,
            expected_manifest_sha256=self.manifest_sha, chunker=chunk_document,
            embed_hybrid=lambda question: ([1.0, 0.0], {"7": 0.5}),
            reranker=self.model, tokenizer=FakeTokenizer(),
            question="comment installer ?", context=self.context,
            generator=generator,
        )
        parameters.update(overrides)
        # side_effect, PAS return_value : les fabriques alimentent self.urls, donc
        # une assertion « aucun client construit » porte réellement une preuve.
        def make_audit(url, *, api_key=""):
            self.urls.append(("audit", url, api_key))
            return self.audit
        def make_query(url, *, api_key=""):
            self.urls.append(("query", url, api_key))
            return self.query
        with patch("rag_hermes.g1_audited_candidates.QdrantAuditClient", side_effect=make_audit), patch(
            "rag_hermes.g1_audited_candidates.QdrantRestClient", side_effect=make_query
        ):
            return run_audited_g1_answer(**parameters)

    def test_cited_answer_is_generated_between_two_audits(self):
        def generate(question, evidence):
            self.events.append(("generate", [chunk.chunk_id for chunk in evidence]))
            return "Installez avec pipx [S1]."

        result = self.run_answer(generate)
        self.assertFalse(result.trace.response.abstained)
        self.assertEqual(result.trace.response.citations[0].chunk_id, self.chunks[0].chunk_id)
        self.assertEqual([chunk.chunk_id for chunk in result.trace.retrieved_chunks], [self.chunks[0].chunk_id])
        self.assertEqual(result.trace.cited_chunks, result.trace.retrieved_chunks)
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "rerank", "generate", "audit",
        ])
        self.assertEqual(self.urls, [
            ("audit", "http://localhost:6333", ""),
            ("query", "http://localhost:6333", ""),
        ])
        # La fenêtre reclassée qui a produit la réponse reste attachée au
        # résultat : un reçu G1 doit pouvoir la reconstituer.
        self.assertEqual(
            [item.chunk.chunk_id for item in result.candidates],
            [self.chunks[0].chunk_id],
        )

    def test_public_candidate_window_takes_no_answer_callback(self):
        # Un paramètre de rappel sur la fonction PUBLIQUE permettrait d'obtenir
        # un résultat porteur des deux VRAIS rapports d'audit tout en
        # contournant les gardes du pilote (générateur appelable, citations
        # strictes) : la voie réponse doit passer par son propre point d'entrée.
        import inspect
        from rag_hermes.g1_audited_candidates import (
            AuditedCandidateWindow, run_audited_g1_candidate_window,
        )
        signature = inspect.signature(run_audited_g1_candidate_window)
        self.assertEqual(
            {name for name in signature.parameters
             if "answer" in name or "generator" in name},
            set(),
        )
        self.assertEqual(signature.return_annotation, "AuditedCandidateWindow")
        window = self.run_window()
        self.assertIs(type(window), AuditedCandidateWindow)

    def test_answer_result_repr_does_not_expose_evidence_or_citations(self):
        # Même politique de représentation que les plans de divergence : un
        # repr accidentel (journal, trace) ne doit pas recopier le texte des
        # preuves ni des citations.
        result = self.run_answer(lambda q, evidence: "Installez avec pipx [S1].")
        rendered = repr(result)
        self.assertNotIn(self.document.content, rendered)
        self.assertNotIn("pipx", rendered)
        self.assertIn("AuditedG1Answer", rendered)
        self.assertIn("citations=1", rendered)

    def test_missing_answer_trace_fails_closed_instead_of_asserting(self):
        # Garde de défense en profondeur : inatteignable par la surface publique
        # (le rappel interne rend toujours une trace), mais un `assert` à sa
        # place disparaîtrait sous `python -O` et laisserait sortir un objet
        # annoncé comme une réponse sans en être une.
        from rag_hermes.generator import GenerationError
        with patch("rag_hermes.g1_audited_candidates.answer_from_evidence", return_value=None):
            with self.assertRaisesRegex(GenerationError, "produced no answer trace"):
                self.run_answer(lambda q, evidence: "Installez avec pipx [S1].")

    def test_multi_chunk_window_lets_the_second_marker_resolve(self):
        # La revendication « les marqueurs sont résolus sur CETTE fenêtre »
        # exige une fenêtre multi-chunks : avec top_k=1 une troncature de
        # l'évidence resterait invisible.
        second = replace(self.document, document_id="other", content="Autre preuve canonique.")
        self.path.write_text("".join(
            json.dumps(asdict(doc)) + "\n" for doc in (self.document, second)
        ), encoding="utf-8")
        self.source_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.chunks = [chunk_document(doc)[0] for doc in (self.document, second)]
        self.points = [chunk_to_point(chunk, [1.0, 0.0]) for chunk in self.chunks]
        self.manifest_sha = verify_index_snapshot(self.chunks, self.points).payload_sha256
        self.audit.points = self.points
        self.query.points = self.points

        seen = []
        def generate(question, evidence):
            seen.append([chunk.document_id for chunk in evidence])
            return "La seconde preuve [S2] le dit."

        result = self.run_answer(generate, top_k=2)
        self.assertEqual(seen, [["guide", "other"]])
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.trace.response.citations[0].document_id, "other")
        self.assertEqual(result.trace.response.citations[0].quote, second.content)

    def test_generator_retained_chunk_mutated_during_closing_audit_is_not_published(self):
        # Le générateur garde une référence au Chunk ; un autre fil peut le
        # modifier APRES le recheck, pendant le scroll final. Le scroll ne
        # regarde que Qdrant, pas les objets Python transmis au générateur.
        retained = []
        original_scroll = self.audit.scroll_page
        scrolls = 0

        def scroll_with_late_mutation(collection, *, limit, offset=None):
            nonlocal scrolls
            scrolls += 1
            if scrolls == 2:
                self.assertEqual(len(retained), 1)
                object.__setattr__(retained[0], "source_uri", "local://forged")
                object.__setattr__(retained[0], "text", "TEXTE FORGE")
            return original_scroll(collection, limit=limit, offset=offset)

        def generate(question, evidence):
            retained.extend(evidence)
            return "Installez avec pipx [S1]."

        with patch.object(self.audit, "scroll_page", side_effect=scroll_with_late_mutation):
            result = self.run_answer(generate)
        self.assertEqual(scrolls, 2)
        self.assertEqual(retained[0].source_uri, "local://forged")
        self.assertEqual(result.trace.response.citations[0].source_uri, "local://guide")
        self.assertEqual(result.trace.response.citations[0].quote, self.document.content)
        self.assertEqual(result.trace.cited_chunks[0].source_uri, "local://guide")
        self.assertEqual(result.trace.retrieved_chunks[0].source_uri, "local://guide")
        self.assertEqual(result.candidates[0].chunk.source_uri, "local://guide")
        self.assertIsNot(result.candidates[0].chunk, retained[0])

    def test_generator_mutating_a_chunk_cannot_rewrite_the_published_citation(self):
        # Les citations sont matérialisées APRÈS le retour du générateur, depuis
        # les objets Chunk qu'il a reçus : un générateur hostile pouvait réécrire
        # le texte cité pendant que l'audit de clôture passait (il compare les
        # payloads de l'index au manifeste, pas les objets candidats).
        def mutate(question, evidence):
            object.__setattr__(evidence[0], "text", "TEXTE INJECTE APRES L'AUDIT")
            return "Installez avec pipx [S1]."

        with self.assertRaisesRegex(PermissionError, "audited manifest"):
            self.run_answer(mutate)
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "rerank",
        ])

    def test_interruption_during_generation_leaves_the_session_terminal(self):
        # `except BaseException` : un Ctrl-C ou un SystemExit doit rendre la
        # session terminale comme une exception ordinaire. `except Exception`
        # laisserait la session réutilisable.
        from rag_hermes.index_integrity import AuditedIndexSession
        real, built = AuditedIndexSession, []

        def make_session(*args, **kwargs):
            session = real(*args, **kwargs)
            built.append(session)
            return session

        for failure in (KeyboardInterrupt, SystemExit, GeneratorExit):
            with self.subTest(failure=failure.__name__):
                built.clear()
                self.events.clear()
                def explode(question, evidence, failure=failure):
                    raise failure()
                with patch("rag_hermes.g1_audited_candidates.AuditedIndexSession",
                           side_effect=make_session):
                    with self.assertRaises(failure):
                        self.run_answer(explode)
                self.assertEqual([event[0] for event in self.events], [
                    "schema", "audit", "dense", "sparse", "rerank",
                ])
                with self.assertRaises(ValueError):
                    built[0].close()
                with self.assertRaises(ValueError):
                    built[0].open()

    def test_session_is_unusable_after_a_generator_failure(self):
        from rag_hermes.index_integrity import AuditedIndexSession
        built = []
        real = AuditedIndexSession

        def make_session(*args, **kwargs):
            session = real(*args, **kwargs)
            built.append(session)
            return session

        def explode(question, evidence):
            raise RuntimeError("generator exploded")

        with patch("rag_hermes.g1_audited_candidates.AuditedIndexSession", side_effect=make_session):
            with self.assertRaisesRegex(RuntimeError, "generator exploded"):
                self.run_answer(explode)
        self.assertEqual(len(built), 1)
        # Pas de second scroll sur abandon, et la session reste terminale : un
        # retry de l'appelant ne doit pas pouvoir bénir une fenêtre ultérieure.
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "rerank",
        ])
        with self.assertRaises(ValueError):
            built[0].close()
        with self.assertRaises(ValueError):
            built[0].open()

    def test_empty_bounded_window_is_not_reported_as_abstention(self):
        self.query.points = []
        calls = []
        # Panne SERVEUR, pas requête client invalide : la couche HTTP traduit
        # GenerationError en 502. Un ValueError nu deviendrait un 400 et
        # imputerait au demandeur une fenêtre vide du pipeline.
        from rag_hermes.generator import GenerationError
        with self.assertRaises(GenerationError) as caught:
            self.run_answer(lambda q, evidence: calls.append(evidence) or "fake [S1]")
        self.assertIn("no verified evidence", str(caught.exception))
        self.assertEqual(calls, [])
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse",
        ])

    def test_generator_without_valid_citation_aborts_without_closing_audit(self):
        from rag_hermes.generator import GenerationError
        with self.assertRaisesRegex(GenerationError, "zero valid citations"):
            self.run_answer(lambda q, evidence: "Unsourced answer")
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "rerank",
        ])

    def test_mixed_valid_and_invalid_citation_does_not_escape_the_audit(self):
        from rag_hermes.generator import GenerationError
        with self.assertRaisesRegex(GenerationError, "invalid citation"):
            self.run_answer(lambda q, evidence: "Une preuve [S1] et une invention [S99].")
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "rerank",
        ])

    def test_closing_divergence_withholds_generated_answer(self):
        def generate(question, evidence):
            self.events.append(("generate", question))
            self.audit.points = [{**self.points[0], "payload": {
                **self.points[0]["payload"], "owner_id": "bob",
            }}]
            return "Installez avec pipx [S1]."

        with self.assertRaisesRegex(AuditedIndexSessionError, "closing audit failed"):
            self.run_answer(generate)
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse", "rerank", "generate", "audit",
        ])

    def test_forged_query_hit_never_reaches_generator(self):
        forged = replace(self.chunks[0], chunk_id="invented")
        self.query.points = [chunk_to_point(forged, [1.0, 0.0])]
        calls = []
        with self.assertRaisesRegex(PermissionError, "audited manifest"):
            self.run_answer(lambda q, evidence: calls.append(evidence) or "fake [S1]")
        self.assertEqual(calls, [])
        self.assertEqual([event[0] for event in self.events], [
            "schema", "audit", "dense", "sparse",
        ])

    def test_generator_receives_reranked_chunks_not_index_order(self):
        second = replace(self.document, document_id="other", content="Autre preuve indépendante.")
        self.path.write_text("".join(
            json.dumps(asdict(doc)) + "\n" for doc in (self.document, second)
        ), encoding="utf-8")
        self.source_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.chunks = [chunk_document(doc)[0] for doc in (self.document, second)]
        self.points = [chunk_to_point(chunk, [1.0, 0.0]) for chunk in self.chunks]
        self.manifest_sha = verify_index_snapshot(self.chunks, self.points).payload_sha256
        self.audit.points = self.points
        self.query.points = self.points

        class ReverseReranker:
            def compute_score(inner_self, pairs, **kwargs):
                self.assertEqual(
                    [passage for _, passage in pairs],
                    [second.content, self.document.content],
                )
                return [0.1, 0.9]

        seen = []
        def generate(question, evidence):
            seen.extend(chunk.document_id for chunk in evidence)
            return "Autre preuve [S1]."

        result = self.run_answer(generate, reranker=ReverseReranker(), top_k=1)
        self.assertEqual(seen, ["guide"])
        self.assertEqual(result.trace.response.citations[0].document_id, "guide")
        self.assertEqual(result.trace.cited_chunks[0].text, self.document.content)

    def test_generator_abstention_is_preserved_as_generator_decision(self):
        from rag_hermes.generator import ABSTENTION_ANSWER
        result = self.run_answer(lambda q, evidence: ABSTENTION_ANSWER)
        self.assertTrue(result.trace.response.abstained)
        self.assertEqual(result.trace.response.citations, ())
        self.assertEqual(len(result.trace.retrieved_chunks), 1)
        self.assertEqual([event[0] for event in self.events][-1], "audit")

    def test_non_callable_generator_is_refused_before_any_read(self):
        # Sans cette garde, l'échec ne sort qu'APRÈS schéma, audit d'ouverture,
        # deux voies de requête et le modèle de reranking, sous forme de
        # TypeError : un câblage invalide consommerait l'index et le modèle.
        with self.assertRaisesRegex(ValueError, "generator must be callable"):
            self.run_answer(object())
        self.assertEqual(self.events, [])
        self.assertEqual(self.urls, [])

    def test_duplicate_point_in_canonical_manifest_refused_before_any_io(self):
        # Un chunker qui émet deux chunks au MÊME point_id empoisonnerait le
        # manifeste par écrasement silencieux (deux chunks annoncés, un seul
        # retenu). Refus explicite AVANT toute construction de session ou I/O
        # Qdrant — sinon la divergence ne sortirait qu'au scroll d'ouverture,
        # avec un autre type d'erreur et après une requête de schéma gâchée.
        def colliding_chunker(document):
            produced = chunk_document(document)
            return [produced[0], produced[0]]
        with self.assertRaisesRegex(ValueError, "duplicate point in canonical manifest"):
            self.run_window(chunker=colliding_chunker)
        # Un preflight de schéma a lieu, mais AUCUN scroll d'audit ni requête :
        # sans la garde, la collision ne sortirait qu'au scroll d'ouverture, en
        # AuditedIndexSessionError (« opening audit failed »), pas en ValueError.
        self.assertEqual([event[0] for event in self.events], ["schema"])

    def test_canonical_source_without_chunks_refused_before_any_io(self):
        # Une source qui ne produit AUCUN chunk n'est pas une fenêtre vide
        # honnête : refus explicite et spécifique à la source AVANT tout I/O,
        # distinct du « empty canonical chunk manifest » du constructeur de
        # session (deux étages fail-closed, libellés distincts).
        with self.assertRaisesRegex(ValueError, "canonical source produced no chunks"):
            self.run_window(chunker=lambda document: [])
        self.assertEqual(self.events, [])



class AuditedWindowCredentialTests(AuditedG1CandidateWindowTests):
    """SEC-03 : la fenêtre G1 porte deux identités de LECTURE distinctes."""

    def test_distinct_read_credentials_reach_their_own_client(self):
        from rag_hermes.qdrant_identity import mint_collection_token
        audit_key = mint_collection_token(
            "g1-secret", collection="audited_chunks", access="r", ttl_seconds=600
        )
        query_key = mint_collection_token(
            "g1-secret", collection="audited_chunks", access="r", ttl_seconds=1200
        )
        self.assertNotEqual(audit_key, query_key)
        self.run_window(audit_api_key=audit_key, query_api_key=query_key)
        self.assertEqual(self.urls, [
            ("audit", "http://localhost:6333", audit_key),
            ("query", "http://localhost:6333", query_key),
        ])

    def test_a_shared_or_write_capable_credential_is_refused_before_any_read(self):
        from rag_hermes.qdrant_identity import mint_collection_token
        read_key = mint_collection_token(
            "g1-secret", collection="audited_chunks", access="r", ttl_seconds=600
        )
        write_key = mint_collection_token(
            "g1-secret", collection="audited_chunks", access="prw", ttl_seconds=600
        )
        for audit_api_key, query_api_key, expected in (
            (read_key, read_key, "distinct"),
            (write_key, read_key, "RAG_QDRANT_G1_AUDIT_API_KEY"),
            (read_key, "", "RAG_QDRANT_G1_QUERY_API_KEY"),
            ("raw-admin-key", read_key, "RAG_QDRANT_G1_AUDIT_API_KEY"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(ValueError) as caught:
                    self.run_window(
                        audit_api_key=audit_api_key, query_api_key=query_api_key
                    )
                message = str(caught.exception)
                self.assertIn(expected, message)
                self.assertNotIn(write_key, message)
                self.assertNotIn("raw-admin-key", message)
                self.assertEqual(self.urls, [], "aucun client ne doit être construit")
                self.assertEqual(self.events, [], "aucune lecture ne doit avoir lieu")

if __name__ == "__main__":
    unittest.main()
