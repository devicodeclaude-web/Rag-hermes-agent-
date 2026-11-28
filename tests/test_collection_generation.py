"""Observation of a collection generation is not an authorization to repair."""
from __future__ import annotations

import unittest


GENERATION = "a8dd7c86-e3e5-48d8-94e2-e27e86d84886"


class ReadOnlyCollectionClient:
    base_url = "https://qdrant.example"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.names = ("physical",)
        self.info = {"config": {"metadata": {"hermes_generation_uuid": GENERATION}}}

    def list_collections(self) -> tuple[str, ...]:
        self.calls.append(("list", ""))
        return self.names

    def get_collection(self, name: str) -> dict:
        self.calls.append(("get", name))
        return self.info


class CollectionGenerationTests(unittest.TestCase):
    def test_observation_requires_physical_name_and_original_generation_marker(self):
        from rag_hermes.collection_generation import observe_collection_generation
        client = ReadOnlyCollectionClient()
        observed = observe_collection_generation(client, "physical")
        self.assertEqual((observed.endpoint, observed.collection, observed.generation),
                         (client.base_url, "physical", GENERATION))
        self.assertEqual(client.calls, [("list", ""), ("get", "physical")])

    def test_alias_is_refused_before_metadata_read(self):
        from rag_hermes.collection_generation import observe_collection_generation
        client = ReadOnlyCollectionClient()
        client.names = ("physical",)
        with self.assertRaisesRegex(ValueError, "physical"):
            observe_collection_generation(client, "alias")
        self.assertEqual(client.calls, [("list", "")])

    def test_missing_malformed_or_legacy_generation_is_refused(self):
        from rag_hermes.collection_generation import observe_collection_generation
        invalid = (None, {}, {"metadata": {}}, {"metadata": {"hermes_generation_uuid": "not-uuid"}},
                   {"metadata": {"hermes_generation_uuid": GENERATION.upper()}},
                   {"metadata": {"hermes_generation_uuid": 1}})
        for config in invalid:
            with self.subTest(config=config):
                client = ReadOnlyCollectionClient()
                client.info = {"config": config}
                with self.assertRaisesRegex(ValueError, "generation"):
                    observe_collection_generation(client, "physical")


if __name__ == "__main__":
    unittest.main()
