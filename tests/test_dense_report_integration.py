from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import unittest
import uuid

from rag_hermes.dense_report import run_dense_evaluation
from rag_hermes.qdrant_repository import QdrantChunkRepository
from rag_hermes.qdrant_rest import QdrantRestClient
from rag_hermes.qdrant_store import deterministic_test_vector

INDEX_SPEC = Path("qdrant/payload-indexes.json")
_DIM = 8


def _embed(text: str) -> list[float]:
    # Deterministic, normalized, NOT a semantic embedding. Proves the persisted
    # dense pipeline (ingest -> Qdrant ANN -> ACL prefilter -> scoring) end to
    # end; it makes no quality claim.
    return deterministic_test_vector(text, dimensions=_DIM)


@unittest.skipUnless(
    os.environ.get("QDRANT_INTEGRATION_URL"), "Qdrant integration disabled"
)
class DenseEvaluationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = QdrantRestClient(os.environ["QDRANT_INTEGRATION_URL"])
        self.collection = "hermes_dense_" + uuid.uuid4().hex[:12]
        self.client.create_collection(self.collection, vector_size=_DIM)
        specification = json.loads(INDEX_SPEC.read_text())
        for index in specification["payload_indexes"]:
            self.client.create_payload_index(
                self.collection, index["field_name"], index["field_schema"]
            )
        self.repository = QdrantChunkRepository(
            self.client, collection=self.collection, embed=_embed
        )

    def tearDown(self) -> None:
        self.client.delete_collection(self.collection)

    def _corpus(self) -> dict[str, dict]:
        answer_text = (
            "To reduce token usage in Hermes, enable automatic compression and "
            "prune old context from the session regularly."
        )
        return {
            "doc-answer": {
                "document_id": "doc-answer",
                "content": answer_text,
                "tenant_id": "public",
                "visibility": "public",
                "owner_id": "evaluator",
                "allowed_groups": [],
                "allowed_users": [],
                "classification": 0,
                "doc_version": 1,
                "source_uri": "evaluation://doc-answer",
            },
            "doc-noise": {
                "document_id": "doc-noise",
                "content": "Weather forecasting relies on atmospheric pressure readings.",
                "tenant_id": "public",
                "visibility": "public",
                "owner_id": "evaluator",
                "allowed_groups": [],
                "allowed_users": [],
                "classification": 0,
                "doc_version": 1,
                "source_uri": "evaluation://doc-noise",
            },
        }

    def _manifest(self) -> dict:
        return {
            "source_revision": "testrev",
            "corpus_manifest_sha": "f" * 64,
        }

    def _answerable_case(self, documents) -> dict:
        content = documents["doc-answer"]["content"]
        start = content.index("enable automatic compression")
        end = start + len("enable automatic compression")
        passage_sha = hashlib.sha256(content[start:end].encode("utf-8")).hexdigest()
        return {
            "case_id": "d-001-en",
            "pair_id": "d-001",
            "language": "en",
            "track": "en2en",
            "category": "simple",
            "access_scope": "public",
            "question": "How can I reduce token usage in Hermes?",
            "question_provenance": "human_task_without_corpus_view",
            "reference_status": "validated",
            "should_abstain": False,
            "unanswerable_reason": None,
            "source_revision": "testrev",
            "corpus_manifest_sha": "f" * 64,
            "relevance_spans": [
                {
                    "document_id": "doc-answer",
                    "start_char": start,
                    "end_char": end,
                    "relevance_grade": 2,
                    "passage_sha256": passage_sha,
                }
            ],
        }

    def test_dense_pipeline_scores_answerable_case_over_real_qdrant(self) -> None:
        documents = self._corpus()
        manifest = self._manifest()
        cases = [self._answerable_case(documents)]

        results = run_dense_evaluation(
            cases,
            documents,
            manifest,
            self.repository,
            k=10,
            minimum_score=0.0,
            limit=10,
        )

        overall = results["overall"]
        self.assertEqual(overall["cases_total"], 1)
        self.assertEqual(overall["cases_answerable"], 1)
        metrics = overall["metrics"]
        # The answer document is persisted and retrievable: recall must be 1.0
        # and there must be no cross-document leak on a public-only corpus.
        self.assertEqual(metrics["recall_at_k"], 1.0)
        self.assertEqual(metrics["leak_count"], 0)
        # Report is organized like the lexical one.
        self.assertIn("en2en", results["by_track"])
        self.assertIn("simple", results["by_category"])

    def test_rejects_synthetic_case_as_not_quality_eligible(self) -> None:
        documents = self._corpus()
        manifest = self._manifest()
        case = self._answerable_case(documents)
        case["question_provenance"] = "synthetic_generated_from_corpus"

        with self.assertRaisesRegex(ValueError, "quality-eligible"):
            run_dense_evaluation(
                [case],
                documents,
                manifest,
                self.repository,
                k=10,
                minimum_score=0.0,
                limit=10,
            )

    def test_rejects_unreviewed_reference(self) -> None:
        documents = self._corpus()
        manifest = self._manifest()
        case = self._answerable_case(documents)
        case["reference_status"] = "pending"

        with self.assertRaisesRegex(ValueError, "reviewed"):
            run_dense_evaluation(
                [case],
                documents,
                manifest,
                self.repository,
                k=10,
                minimum_score=0.0,
                limit=10,
            )


if __name__ == "__main__":
    unittest.main()
