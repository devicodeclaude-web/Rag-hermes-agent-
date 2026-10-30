from __future__ import annotations

from copy import deepcopy
import json
import unittest
from pathlib import Path
from typing import Any

from rag_hermes.qdrant_provision import QdrantProvisionError, provision_collection


SPECIFICATION = json.loads(
    Path("qdrant/payload-indexes.json").read_text(encoding="utf-8")
)


class StatefulFakeClient:
    def __init__(self) -> None:
        self.exists = False
        self.vectors: dict[str, Any] | None = None
        self.payload_schema: dict[str, Any] = {}
        self.calls: list[tuple[Any, ...]] = []

    def collection_exists(self, collection: str) -> bool:
        self.calls.append(("exists", collection))
        return self.exists

    def create_collection(
        self, collection: str, *, vector_size: int, distance: str = "Cosine"
    ) -> dict[str, Any]:
        self.calls.append(("create_collection", collection, vector_size, distance))
        self.exists = True
        self.vectors = {"dense": {"size": vector_size, "distance": distance}}
        return {"result": True}

    def create_payload_index(
        self,
        collection: str,
        field_name: str,
        field_schema: str | dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(("create_index", collection, field_name, field_schema))
        if isinstance(field_schema, str):
            self.payload_schema[field_name] = {
                "data_type": field_schema,
                "points": 0,
            }
        else:
            self.payload_schema[field_name] = {
                "data_type": field_schema["type"],
                "params": dict(field_schema),
                "points": 0,
            }
        return {"result": {"status": "completed"}}

    def get_collection(self, collection: str) -> dict[str, Any]:
        self.calls.append(("get_collection", collection))
        if not self.exists:
            raise RuntimeError("collection missing")
        return {
            "status": "green",
            "config": {"params": {"vectors": self.vectors}},
            "payload_schema": (
                dict(self.payload_schema)
                if isinstance(self.payload_schema, dict)
                else self.payload_schema
            ),
        }


class ProvisionCollectionTests(unittest.TestCase):
    def test_absent_collection_is_created_from_exact_specification(self) -> None:
        client = StatefulFakeClient()

        report = provision_collection(
            client,
            collection="hermes_chunks_v1",
            vector_size=1024,
            specification=SPECIFICATION,
        )

        self.assertTrue(client.exists)
        self.assertEqual(
            client.vectors,
            {"dense": {"size": 1024, "distance": "Cosine"}},
        )
        created_indexes = [
            call[2] for call in client.calls if call[0] == "create_index"
        ]
        expected_indexes = [
            item["field_name"] for item in SPECIFICATION["payload_indexes"]
        ]
        self.assertEqual(created_indexes, expected_indexes)
        self.assertTrue(report["collection_created"])
        self.assertEqual(report["indexes_created"], expected_indexes)
        self.assertTrue(report["ready"])

    def test_existing_wrong_vector_size_fails_before_any_index_mutation(self) -> None:
        client = StatefulFakeClient()
        client.exists = True
        client.vectors = {"dense": {"size": 8, "distance": "Cosine"}}

        with self.assertRaisesRegex(QdrantProvisionError, "1024"):
            provision_collection(
                client,
                collection="hermes_chunks_v1",
                vector_size=1024,
                specification=SPECIFICATION,
            )

        mutations = [call for call in client.calls if call[0] == "create_index"]
        self.assertEqual(mutations, [])

    def test_existing_wrong_vector_distance_fails_before_any_mutation(self) -> None:
        client = StatefulFakeClient()
        client.exists = True
        client.vectors = {"dense": {"size": 1024, "distance": "Dot"}}

        with self.assertRaisesRegex(QdrantProvisionError, "Cosine"):
            provision_collection(
                client,
                collection="hermes_chunks_v1",
                vector_size=1024,
                specification=SPECIFICATION,
            )

        mutations = [call for call in client.calls if call[0] == "create_index"]
        self.assertEqual(mutations, [])

    def test_existing_wrong_index_fails_before_creating_missing_indexes(self) -> None:
        client = StatefulFakeClient()
        client.exists = True
        client.vectors = {"dense": {"size": 1024, "distance": "Cosine"}}
        client.payload_schema = {
            "tenant_id": {"data_type": "keyword", "points": 0}
        }

        with self.assertRaisesRegex(QdrantProvisionError, "tenant_id"):
            provision_collection(
                client,
                collection="hermes_chunks_v1",
                vector_size=1024,
                specification=SPECIFICATION,
            )

        mutations = [call for call in client.calls if call[0] == "create_index"]
        self.assertEqual(mutations, [])

    def test_existing_non_tenant_index_marked_tenant_fails_before_mutation(self) -> None:
        client = StatefulFakeClient()
        client.exists = True
        client.vectors = {"dense": {"size": 1024, "distance": "Cosine"}}
        client.payload_schema = {
            "visibility": {
                "data_type": "keyword",
                "params": {"type": "keyword", "is_tenant": True},
                "points": 0,
            }
        }

        with self.assertRaisesRegex(QdrantProvisionError, "visibility"):
            provision_collection(
                client,
                collection="hermes_chunks_v1",
                vector_size=1024,
                specification=SPECIFICATION,
            )

        mutations = [call for call in client.calls if call[0] == "create_index"]
        self.assertEqual(mutations, [])

    def test_malformed_existing_payload_schema_fails_before_mutation(self) -> None:
        client = StatefulFakeClient()
        client.exists = True
        client.vectors = {"dense": {"size": 1024, "distance": "Cosine"}}
        client.payload_schema = []  # type: ignore[assignment]

        with self.assertRaisesRegex(QdrantProvisionError, "payload_schema"):
            provision_collection(
                client,
                collection="hermes_chunks_v1",
                vector_size=1024,
                specification=SPECIFICATION,
            )

        mutations = [call for call in client.calls if call[0] == "create_index"]
        self.assertEqual(mutations, [])

    def test_drifted_specification_is_rejected_before_creating_collection(self) -> None:
        client = StatefulFakeClient()
        drifted = {
            **SPECIFICATION,
            "payload_indexes": SPECIFICATION["payload_indexes"][:-1],
        }

        with self.assertRaisesRegex(QdrantProvisionError, "specification"):
            provision_collection(
                client,
                collection="hermes_chunks_v1",
                vector_size=1024,
                specification=drifted,
            )

        mutations = [
            call
            for call in client.calls
            if call[0] in {"create_collection", "create_index"}
        ]
        self.assertEqual(mutations, [])

    def test_every_malformed_manifest_is_rejected_before_any_client_call(self) -> None:
        cases: list[tuple[str, object]] = []

        bad_collection_type = deepcopy(SPECIFICATION)
        bad_collection_type["collection"] = 123
        cases.append(("collection type", bad_collection_type))

        unknown_top_level = deepcopy(SPECIFICATION)
        unknown_top_level["unexpected"] = True
        cases.append(("unknown top-level property", unknown_top_level))

        bad_verified_against = deepcopy(SPECIFICATION)
        bad_verified_against["verified_against"] = ["Qdrant 1.19.0"]
        cases.append(("verified_against type", bad_verified_against))

        bad_minimum_version = deepcopy(SPECIFICATION)
        bad_minimum_version["minimum_version_for_is_tenant"] = False
        cases.append(("minimum version type", bad_minimum_version))

        unknown_index_property = deepcopy(SPECIFICATION)
        unknown_index_property["payload_indexes"][0]["unexpected"] = True
        cases.append(("unknown index property", unknown_index_property))

        string_is_tenant = deepcopy(SPECIFICATION)
        string_is_tenant["payload_indexes"][0]["field_schema"]["is_tenant"] = "false"
        cases.append(("non-boolean is_tenant", string_is_tenant))

        unknown_schema_property = deepcopy(SPECIFICATION)
        unknown_schema_property["payload_indexes"][0]["field_schema"]["extra"] = 1
        cases.append(("unknown schema property", unknown_schema_property))

        object_for_non_tenant = deepcopy(SPECIFICATION)
        object_for_non_tenant["payload_indexes"][1]["field_schema"] = {
            "type": "keyword",
            "is_tenant": False,
        }
        cases.append(("non-canonical non-tenant schema", object_for_non_tenant))

        for label, malformed in cases:
            with self.subTest(label=label):
                client = StatefulFakeClient()
                with self.assertRaisesRegex(QdrantProvisionError, "specification"):
                    provision_collection(
                        client,
                        collection="hermes_chunks_v1",
                        vector_size=1024,
                        specification=malformed,  # type: ignore[arg-type]
                    )
                self.assertEqual(client.calls, [])

    def test_partial_run_resumes_by_creating_only_missing_indexes(self) -> None:
        client = StatefulFakeClient()
        client.exists = True
        client.vectors = {"dense": {"size": 1024, "distance": "Cosine"}}
        for index in SPECIFICATION["payload_indexes"][:3]:
            client.create_payload_index(
                "hermes_chunks_v1", index["field_name"], index["field_schema"]
            )
        client.calls.clear()

        report = provision_collection(
            client,
            collection="hermes_chunks_v1",
            vector_size=1024,
            specification=SPECIFICATION,
        )

        expected_missing = [
            item["field_name"] for item in SPECIFICATION["payload_indexes"][3:]
        ]
        created = [call[2] for call in client.calls if call[0] == "create_index"]
        self.assertEqual(created, expected_missing)
        self.assertEqual(report["indexes_created"], expected_missing)
        self.assertTrue(report["ready"])

    def test_second_run_is_a_noop_and_reports_no_created_resources(self) -> None:
        client = StatefulFakeClient()
        provision_collection(
            client,
            collection="hermes_chunks_v1",
            vector_size=1024,
            specification=SPECIFICATION,
        )
        calls_after_first_run = len(client.calls)

        report = provision_collection(
            client,
            collection="hermes_chunks_v1",
            vector_size=1024,
            specification=SPECIFICATION,
        )

        second_run_calls = client.calls[calls_after_first_run:]
        mutations = [
            call
            for call in second_run_calls
            if call[0] in {"create_collection", "create_index"}
        ]
        self.assertEqual(mutations, [])
        self.assertFalse(report["collection_created"])
        self.assertEqual(report["indexes_created"], [])
        self.assertTrue(report["ready"])


if __name__ == "__main__":
    unittest.main()
