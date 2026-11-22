"""The audit reader must not be able to mutate the index at all.

SEC-03. The previous audit client inherited every method of the read/write
REST client, so an operator credential with write rights — or a stray call in
an audit script — could upsert or delete. The audit client now owns only an
HTTP transport and exposes exactly one capability: unfiltered scrolling.
"""
from __future__ import annotations

import unittest

from rag_hermes.qdrant_rest import (
    QdrantAuditClient,
    QdrantHttpTransport,
    QdrantRestClient,
)

MUTATIONS = (
    "upsert", "delete_points", "delete_collection", "create_collection",
    "create_payload_index", "retrieve_points", "query", "query_sparse",
    "scroll", "scroll_filtered_page", "collection_exists", "get_collection",
)


class QdrantAuditClientSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = QdrantAuditClient("http://127.0.0.1:6333", api_key="audit-token")

    def test_exposes_only_unfiltered_scrolling(self) -> None:
        self.assertTrue(callable(self.client.scroll_page))
        for name in MUTATIONS:
            with self.subTest(name=name):
                self.assertFalse(hasattr(self.client, name), name)

    def test_is_not_a_read_write_client_in_disguise(self) -> None:
        self.assertNotIsInstance(self.client, QdrantRestClient)
        self.assertFalse(issubclass(QdrantAuditClient, QdrantRestClient))

    def test_no_object_it_holds_can_mutate_the_index(self) -> None:
        """Composition, not hiding: the whole object graph is mutation-free."""
        for attribute, value in vars(self.client).items():
            for name in MUTATIONS:
                with self.subTest(attribute=attribute, name=name):
                    self.assertFalse(hasattr(value, name), f"{attribute}.{name}")

    def test_carries_its_own_credential_and_validates_the_endpoint(self) -> None:
        self.assertEqual(self.client.base_url, "http://127.0.0.1:6333")
        self.assertEqual(self.client._transport._api_key, "audit-token")
        for url in ("http://qdrant.example:6333", "https://user:pass@qdrant.example"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                QdrantAuditClient(url, api_key="audit-token")

    def test_the_transport_sends_the_audit_key_in_the_api_key_header(self) -> None:
        transport = QdrantHttpTransport("http://127.0.0.1:6333", api_key="audit-token")
        captured: dict[str, object] = {}

        class _Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b'{"result": {"points": [], "next_page_offset": null}}'

        def fake_open(request, timeout=None):
            captured["headers"] = dict(request.headers)
            captured["url"] = request.full_url
            return _Response()

        transport._opener.open = fake_open  # type: ignore[assignment]
        transport.request("POST", "/collections/chunks/points/scroll", {"limit": 1})
        self.assertEqual(captured["headers"].get("Api-key"), "audit-token")
        self.assertEqual(
            captured["url"], "http://127.0.0.1:6333/collections/chunks/points/scroll"
        )


class QdrantAuditScrollPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = QdrantAuditClient("http://127.0.0.1:6333")

    def patch_request(self, result):
        self.client._transport.request = lambda *_a, **_k: {"result": result}

    def test_cursor_round_trip_requests_payload_without_vectors(self) -> None:
        calls = []

        def request(method, path, body):
            calls.append((method, path, body))
            return {"result": {"points": [{"id": "one", "payload": {}}],
                               "next_page_offset": "next-id"}}

        self.client._transport.request = request
        points, cursor = self.client.scroll_page("chunks", limit=3, offset="start-id")
        self.assertEqual(points, [{"id": "one", "payload": {}}])
        self.assertEqual(cursor, "next-id")
        self.assertEqual(calls, [("POST", "/collections/chunks/points/scroll", {
            "limit": 3, "offset": "start-id", "with_payload": True,
            "with_vector": False,
        })])

    def test_rejects_malformed_results(self) -> None:
        for invalid in (
            None, [], {}, {"points": None}, {"points": {}}, {"points": []},
            {"points": [], "next_page_offset": []},
            {"points": [], "next_page_offset": {}},
            {"points": [], "next_page_offset": 1.5},
            {"points": [], "next_page_offset": True},
        ):
            with self.subTest(invalid=invalid):
                self.patch_request(invalid)
                with self.assertRaisesRegex(RuntimeError, "malformed"):
                    self.client.scroll_page("chunks", limit=2)

    def test_rejects_an_explicit_error_status_even_with_matching_points(self) -> None:
        self.client._transport.request = lambda *_a, **_k: {
            "status": "error", "result": {
                "points": [{"id": "one", "payload": {}}],
                "next_page_offset": None,
            },
        }
        with self.assertRaisesRegex(RuntimeError, "status"):
            self.client.scroll_page("chunks", limit=2)

    def test_rejects_a_self_referential_cursor(self) -> None:
        self.patch_request({"points": [{"id": "a"}], "next_page_offset": "same-id"})
        with self.assertRaisesRegex(RuntimeError, "cursor"):
            self.client.scroll_page("chunks", limit=1, offset="same-id")

    def test_rejects_an_oversized_page(self) -> None:
        self.patch_request({
            "points": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "next_page_offset": None,
        })
        with self.assertRaisesRegex(RuntimeError, "more points than"):
            self.client.scroll_page("chunks", limit=2)

    def test_refuses_invalid_limit_or_offset(self) -> None:
        for limit in (0, -1, 1001):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(ValueError, "bounded scroll limit"):
                    self.client.scroll_page("chunks", limit=limit)
        for offset in (1.5, True, [], {}):
            with self.subTest(offset=offset):
                with self.assertRaisesRegex(ValueError, "invalid scroll offset"):
                    self.client.scroll_page("chunks", limit=2, offset=offset)


if __name__ == "__main__":
    unittest.main()
