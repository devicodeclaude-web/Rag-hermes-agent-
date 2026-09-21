"""Preuve ACL de bout en bout sur Qdrant reel.

Contrairement a test_qdrant_integration (trois Chunk fabriques a la main), ce
test part des VRAIS documents fixtures, les fait passer par l'ingestion reelle
(chunk_document), les persiste dans Qdrant via chunk_to_point + upsert, puis
interroge avec un filtre ACL. Le cas adverse est volontaire : la requete d'Alpha
utilise le vecteur EXACT du chunk secret de Beta, donc seul le filtre ACL
(et non la distance vectorielle) peut empecher la fuite.

Chaine couverte : load_documents -> chunk_document -> chunk_to_point
-> upsert(Qdrant reel) -> query(filtre ACL) -> verification d'absence de fuite.
"""
from __future__ import annotations

import json
import os
import unittest
import uuid
from pathlib import Path

from rag_hermes.acl import AuthorizationContext
from rag_hermes.dataset import load_documents
from rag_hermes.ingestion import chunk_document
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_rest import QdrantRestClient
from rag_hermes.qdrant_store import chunk_to_point, deterministic_test_vector

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data/fixtures/private_and_synthetic_documents.jsonl"
DIMENSIONS = 8


@unittest.skipUnless(
    os.environ.get("QDRANT_INTEGRATION_URL"), "Qdrant integration disabled"
)
class EndToEndAclTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = QdrantRestClient(os.environ["QDRANT_INTEGRATION_URL"])
        self.collection = "hermes_e2e_acl_" + uuid.uuid4().hex[:12]
        self.documents = load_documents(FIXTURES)
        self.chunks = [
            chunk
            for document in self.documents
            for chunk in chunk_document(document, max_tokens=64, overlap_tokens=8)
        ]
        # index texte -> chunk pour retrouver un vecteur exact
        self.by_document = {}
        for chunk in self.chunks:
            self.by_document.setdefault(chunk.document_id, chunk)

        self.client.create_collection(self.collection, vector_size=DIMENSIONS)
        specification = json.loads(Path(ROOT / "qdrant/payload-indexes.json").read_text())
        for index in specification["payload_indexes"]:
            self.client.create_payload_index(
                self.collection, index["field_name"], index["field_schema"]
            )
        self.client.upsert(
            self.collection,
            [
                chunk_to_point(chunk, deterministic_test_vector(chunk.text, dimensions=DIMENSIONS))
                for chunk in self.chunks
            ],
        )

    def tearDown(self) -> None:
        self.client.delete_collection(self.collection)

    def test_alpha_query_with_beta_secret_vector_never_leaks_beta(self) -> None:
        beta_chunk = self.by_document["tenant-beta-secret"]
        # cas adverse : on interroge AVEC le vecteur exact du secret Beta
        beta_vector = deterministic_test_vector(beta_chunk.text, dimensions=DIMENSIONS)

        alpha = AuthorizationContext("alpha", "alice", ("admins",), 2)
        points = self.client.query(
            self.collection,
            beta_vector,
            query_filter=build_qdrant_filter(alpha),
            limit=50,
        )
        tenants = {point["payload"]["tenant_id"] for point in points}
        documents = {point["payload"]["document_id"] for point in points}

        self.assertNotIn("beta", tenants, "fuite inter-tenant : Beta visible par Alpha")
        self.assertNotIn("tenant-beta-secret", documents)
        # Alpha ne doit voir que son tenant ou le public
        self.assertTrue(tenants.issubset({"alpha", "public"}), tenants)

    def test_owner_recovers_own_private_document_end_to_end(self) -> None:
        jarvis = self.by_document["jarvis-placeholder"]
        vector = deterministic_test_vector(jarvis.text, dimensions=DIMENSIONS)

        owner = AuthorizationContext("personal", "user", ("owners",), 2)
        points = self.client.query(
            self.collection,
            vector,
            query_filter=build_qdrant_filter(owner),
            limit=50,
        )
        documents = {point["payload"]["document_id"] for point in points}
        self.assertIn("jarvis-placeholder", documents)

    def test_low_clearance_owner_is_denied_high_classification(self) -> None:
        jarvis = self.by_document["jarvis-placeholder"]
        vector = deterministic_test_vector(jarvis.text, dimensions=DIMENSIONS)

        low = AuthorizationContext("personal", "user", ("owners",), 0)
        points = self.client.query(
            self.collection,
            vector,
            query_filter=build_qdrant_filter(low),
            limit=50,
        )
        documents = {point["payload"]["document_id"] for point in points}
        self.assertNotIn("jarvis-placeholder", documents)


if __name__ == "__main__":
    unittest.main()
