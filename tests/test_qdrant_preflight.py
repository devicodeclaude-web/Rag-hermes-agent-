"""Preflight checks for a Qdrant collection used as an ACL-bearing backend.

Non-negotiable rule 5 of the README: `tenant_id` must be indexed in Qdrant and
declared as a tenant field. These tests pin the *fail-closed* behaviour: a
misconfigured collection must be refused at startup, not silently accepted and
discovered later at query time.

The payload_schema shapes asserted here were captured from a real Qdrant 1.19.0
aarch64 server (see tests/test_qdrant_preflight_integration.py for the live
proof), not invented.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from rag_hermes.qdrant_preflight import (
    REQUIRED_PAYLOAD_INDEXES,
    QdrantPreflightError,
    verify_collection_ready,
)


def _schema(**overrides: Any) -> dict[str, Any]:
    """A fully compliant payload_schema, as returned by Qdrant 1.19.0."""
    schema: dict[str, Any] = {}
    for field, expected in REQUIRED_PAYLOAD_INDEXES.items():
        entry: dict[str, Any] = {"data_type": expected.data_type, "points": 0}
        if expected.is_tenant:
            entry["params"] = {"type": expected.data_type, "is_tenant": True}
        schema[field] = entry
    schema.update(overrides)
    return schema


def _collection(
    *,
    payload_schema: dict[str, Any] | None = None,
    vectors: Any = None,
) -> dict[str, Any]:
    if vectors is None:
        vectors = {"dense": {"size": 1024, "distance": "Cosine"}}
    return {
        "status": "green",
        "points_count": 0,
        "config": {"params": {"vectors": vectors}},
        "payload_schema": _schema() if payload_schema is None else payload_schema,
    }


class FakeClient:
    """Minimal stand-in exposing only what the preflight is allowed to use."""

    def __init__(self, response: dict[str, Any] | Exception):
        self.response = response
        self.calls: list[str] = []

    def get_collection(self, collection: str) -> dict[str, Any]:
        self.calls.append(collection)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ContractTests(unittest.TestCase):
    def test_required_indexes_match_the_committed_qdrant_spec(self) -> None:
        # The module contract and qdrant/payload-indexes.json must not drift.
        spec = json.loads(
            Path("qdrant/payload-indexes.json").read_text(encoding="utf-8")
        )
        declared: dict[str, tuple[str, bool]] = {}
        for item in spec["payload_indexes"]:
            field_schema = item["field_schema"]
            if isinstance(field_schema, str):
                declared[item["field_name"]] = (field_schema, False)
            else:
                declared[item["field_name"]] = (
                    field_schema["type"],
                    bool(field_schema.get("is_tenant", False)),
                )

        contract = {
            name: (expected.data_type, expected.is_tenant)
            for name, expected in REQUIRED_PAYLOAD_INDEXES.items()
        }
        self.assertEqual(contract, declared)

    def test_tenant_id_is_required_as_a_tenant_field(self) -> None:
        self.assertTrue(REQUIRED_PAYLOAD_INDEXES["tenant_id"].is_tenant)


class VerifyCollectionReadyTests(unittest.TestCase):
    def test_compliant_collection_is_accepted_and_reports_what_it_checked(self) -> None:
        client = FakeClient(_collection())
        report = verify_collection_ready(client, "hermes_chunks_v1")
        self.assertEqual(client.calls, ["hermes_chunks_v1"])
        self.assertEqual(report["collection"], "hermes_chunks_v1")
        self.assertEqual(report["vector_name"], "dense")
        self.assertTrue(report["tenant_index"])
        self.assertEqual(
            sorted(report["verified_indexes"]),
            sorted(REQUIRED_PAYLOAD_INDEXES),
        )

    def test_missing_collection_is_refused_with_actionable_message(self) -> None:
        client = FakeClient(
            RuntimeError("Qdrant HTTP 404: Collection `x` doesn't exist!")
        )
        with self.assertRaises(QdrantPreflightError) as caught:
            verify_collection_ready(client, "x")
        self.assertIn("does not exist", str(caught.exception))

    def test_unreachable_server_is_refused_not_swallowed(self) -> None:
        client = FakeClient(RuntimeError("Qdrant unavailable: [Errno 111] refused"))
        with self.assertRaises(QdrantPreflightError) as caught:
            verify_collection_ready(client, "hermes_chunks_v1")
        self.assertIn("unavailable", str(caught.exception).lower())

    def test_tenant_id_indexed_without_is_tenant_is_refused(self) -> None:
        # This is the dangerous case: the field is indexed and queries work,
        # but Qdrant does not enforce tenant-aware placement.
        schema = _schema(tenant_id={"data_type": "keyword", "points": 0})
        client = FakeClient(_collection(payload_schema=schema))
        with self.assertRaises(QdrantPreflightError) as caught:
            verify_collection_ready(client, "hermes_chunks_v1")
        message = str(caught.exception)
        self.assertIn("tenant_id", message)
        self.assertIn("is_tenant", message)

    def test_tenant_id_with_is_tenant_false_is_refused(self) -> None:
        schema = _schema(
            tenant_id={
                "data_type": "keyword",
                "params": {"type": "keyword", "is_tenant": False},
                "points": 0,
            }
        )
        client = FakeClient(_collection(payload_schema=schema))
        with self.assertRaisesRegex(QdrantPreflightError, "is_tenant"):
            verify_collection_ready(client, "hermes_chunks_v1")

    def test_missing_acl_index_is_refused_and_named(self) -> None:
        schema = _schema()
        del schema["classification"]
        client = FakeClient(_collection(payload_schema=schema))
        with self.assertRaises(QdrantPreflightError) as caught:
            verify_collection_ready(client, "hermes_chunks_v1")
        self.assertIn("classification", str(caught.exception))

    def test_every_required_index_is_individually_enforced(self) -> None:
        # No field may be quietly optional: dropping any one must fail.
        for field in REQUIRED_PAYLOAD_INDEXES:
            with self.subTest(field=field):
                schema = _schema()
                del schema[field]
                client = FakeClient(_collection(payload_schema=schema))
                with self.assertRaises(QdrantPreflightError) as caught:
                    verify_collection_ready(client, "hermes_chunks_v1")
                self.assertIn(field, str(caught.exception))

    def test_wrong_index_data_type_is_refused(self) -> None:
        # classification drives the clearance range filter; a keyword index
        # would make `range` comparisons meaningless.
        schema = _schema(classification={"data_type": "keyword", "points": 0})
        client = FakeClient(_collection(payload_schema=schema))
        with self.assertRaises(QdrantPreflightError) as caught:
            verify_collection_ready(client, "hermes_chunks_v1")
        message = str(caught.exception)
        self.assertIn("classification", message)
        self.assertIn("integer", message)

    def test_missing_named_dense_vector_is_refused(self) -> None:
        client = FakeClient(_collection(vectors={"other": {"size": 4}}))
        with self.assertRaises(QdrantPreflightError) as caught:
            verify_collection_ready(client, "hermes_chunks_v1")
        self.assertIn("dense", str(caught.exception))

    def test_unnamed_single_vector_config_is_refused(self) -> None:
        # A legacy unnamed-vector collection cannot serve `using: "dense"`.
        client = FakeClient(_collection(vectors={"size": 1024, "distance": "Cosine"}))
        with self.assertRaises(QdrantPreflightError):
            verify_collection_ready(client, "hermes_chunks_v1")

    def test_absent_payload_schema_is_refused_not_treated_as_empty(self) -> None:
        collection = _collection()
        del collection["payload_schema"]
        client = FakeClient(collection)
        with self.assertRaises(QdrantPreflightError):
            verify_collection_ready(client, "hermes_chunks_v1")

    def test_malformed_response_is_refused_fail_closed(self) -> None:
        for bad in ([], "ok", None, 7):
            with self.subTest(bad=bad):
                client = FakeClient(bad)  # type: ignore[arg-type]
                with self.assertRaises(QdrantPreflightError):
                    verify_collection_ready(client, "hermes_chunks_v1")

    def test_malformed_schema_entry_is_refused_not_coerced(self) -> None:
        schema = _schema(visibility="keyword")
        client = FakeClient(_collection(payload_schema=schema))
        with self.assertRaises(QdrantPreflightError):
            verify_collection_ready(client, "hermes_chunks_v1")

    def test_empty_collection_name_is_refused(self) -> None:
        client = FakeClient(_collection())
        with self.assertRaises(ValueError):
            verify_collection_ready(client, "  ")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
