import json
import os
import threading
import traceback
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

from rag_hermes.acl import AuthorizationContext
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_rest import QdrantRestClient


class RecordingHandler(BaseHTTPRequestHandler):
    requests = []
    exists_result: Any = True
    seen_keys: list[str | None] = []
    redirect_target: str | None = None
    error_detail: str | None = None

    def log_message(self, format, *args):
        return

    def _record(self):
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.requests.append((self.command, self.path, body))
        self.__class__.seen_keys.append(self.headers.get("api-key"))
        if self.__class__.redirect_target is not None:
            self.send_response(302)
            self.send_header("Location", self.__class__.redirect_target)
            self.end_headers()
            return
        if self.__class__.error_detail is not None:
            detail = self.__class__.error_detail.encode()
            self.send_response(403, "REMOTE-SENTINEL")
            self.send_header("content-length", str(len(detail)))
            self.end_headers()
            self.wfile.write(detail)
            return
        result = (
            {"exists": self.__class__.exists_result}
            if self.path.endswith("/exists")
            else [] if self.path.endswith("/points") and self.command == "POST"
            else {"points": []}
        )
        response = {"result": result, "status": "ok", "time": 0.0}
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    do_PUT = _record
    do_POST = _record
    do_DELETE = _record
    do_GET = _record


class QdrantRestClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RecordingHandler.requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        RecordingHandler.requests.clear()
        RecordingHandler.seen_keys.clear()
        RecordingHandler.redirect_target = None
        RecordingHandler.error_detail = None
        RecordingHandler.exists_result = True
        self.client = QdrantRestClient(self.base_url)

    def test_endpoint_refuses_remote_cleartext_and_url_credentials(self):
        invalid = (
            "http://qdrant.example:6333", "http://user@127.0.0.1:6333",
            "https://qdrant.example/path", "https://qdrant.example?token=secret",
            "https://qdrant.example#fragment", "qdrant.example:6333",
            "http://127.0.0.1:invalid", "http://127.0.0.1:6333\nHost: evil",
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                QdrantRestClient(url)
        self.assertEqual(RecordingHandler.requests, [])
        self.assertEqual(QdrantRestClient("https://qdrant.example:6333/").base_url,
                         "https://qdrant.example:6333")

    def test_invalid_url_does_not_echo_embedded_secret_in_traceback(self):
        with self.assertRaises(ValueError) as caught:
            QdrantRestClient("http://127.0.0.1:URL-EMBEDDED-SECRET")
        self.assertNotIn(
            "URL-EMBEDDED-SECRET", "".join(traceback.format_exception(caught.exception)),
        )

    def test_api_key_is_sent_and_invalid_key_is_rejected_without_leak(self):
        client = QdrantRestClient(self.base_url, api_key="example-key")
        self.assertTrue(client.collection_exists("chunks"))
        self.assertEqual(RecordingHandler.seen_keys, ["example-key"])
        for key in ("secret\nInjected: yes", "bad\rkey", "space key", "é"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "api_key") as caught:
                QdrantRestClient(self.base_url, api_key=key)
            self.assertNotIn(key, str(caught.exception))

    def test_redirect_is_not_followed_with_api_key(self):
        RecordingHandler.redirect_target = self.base_url + "/unexpected"
        client = QdrantRestClient(self.base_url, api_key="example-key")
        with self.assertRaises(RuntimeError):
            client.collection_exists("chunks")
        self.assertEqual(len(RecordingHandler.requests), 1)
        self.assertEqual(RecordingHandler.seen_keys, ["example-key"])

    def test_loopback_key_never_goes_to_environment_proxy(self):
        for host in ("127.0.0.1", "localhost", "[::1]"):
            with self.subTest(host=host):
                RecordingHandler.requests.clear()
                RecordingHandler.seen_keys.clear()
                with patch.dict(os.environ, {
                    "http_proxy": self.base_url, "no_proxy": "", "NO_PROXY": "",
                }, clear=True):
                    client = QdrantRestClient(
                        f"http://{host}:1", api_key="example-key", timeout=1,
                    )
                    with self.assertRaises(RuntimeError):
                        client.collection_exists("chunks")
                self.assertEqual(RecordingHandler.requests, [])
                self.assertEqual(RecordingHandler.seen_keys, [])

    def test_http_error_does_not_reveal_remote_detail(self):
        RecordingHandler.error_detail = "CAUSE-DETAIL-MUST-NOT-LEAK"
        with self.assertRaisesRegex(RuntimeError, "Qdrant HTTP 403") as caught:
            self.client.collection_exists("chunks")
        self.assertNotIn("CAUSE-DETAIL-MUST-NOT-LEAK", str(caught.exception))
        self.assertNotIn("REMOTE-SENTINEL", "".join(traceback.format_exception(caught.exception)))

    def test_create_collection_sends_named_dense_vector_config(self):
        self.client.create_collection("chunks", vector_size=4)
        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual((method, path), ("PUT", "/collections/chunks"))
        self.assertEqual(body["vectors"], {"dense": {"size": 4, "distance": "Cosine"}})

    def test_create_collection_can_declare_named_sparse_vector(self):
        self.client.create_collection("hybrid", vector_size=4, sparse=True)
        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual((method, path), ("PUT", "/collections/hybrid"))
        self.assertEqual(body, {
            "vectors": {"dense": {"size": 4, "distance": "Cosine"}},
            "sparse_vectors": {"sparse": {}},
        })

    def test_get_collection_reads_collection_metadata(self):
        result = self.client.get_collection("chunks with/slash")
        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual(
            (method, path, body),
            ("GET", "/collections/chunks%20with%2Fslash", {}),
        )
        self.assertEqual(result, {"points": []})

    def test_collection_exists_reads_strict_boolean_result(self):
        exists = self.client.collection_exists("chunks with/slash")
        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual(
            (method, path, body),
            ("GET", "/collections/chunks%20with%2Fslash/exists", {}),
        )
        self.assertIs(exists, True)

    def test_collection_exists_preserves_false(self):
        RecordingHandler.exists_result = False
        self.assertIs(self.client.collection_exists("missing"), False)

    def test_collection_exists_rejects_non_boolean_values(self):
        for invalid in (None, 0, 1, "false", [], {}):
            with self.subTest(invalid=invalid):
                RecordingHandler.exists_result = invalid
                with self.assertRaisesRegex(RuntimeError, "malformed"):
                    self.client.collection_exists("chunks")

    def test_create_tenant_payload_index_preserves_is_tenant(self):
        self.client.create_payload_index(
            "chunks", "tenant_id", {"type": "keyword", "is_tenant": True}
        )
        _, path, body = RecordingHandler.requests[-1]
        self.assertEqual(path, "/collections/chunks/index?wait=true")
        self.assertEqual(body["field_schema"]["is_tenant"], True)

    def test_filtered_page_preserves_cursor_and_requires_terminal_marker(self):
        expected_filter = {"must": [{"key": "tenant_id", "match": {"value": "a"}}]}
        original = self.client._request
        responses = iter([
            {"status": "ok", "result": {"points": [{"id": "a", "payload": {}}], "next_page_offset": "b"}},
            {"status": "ok", "result": {"points": [], "next_page_offset": None}},
        ])
        self.client._request = lambda method, path, body: (
            RecordingHandler.requests.append((method, path, body)) or next(responses)
        )
        try:
            first, cursor = self.client.scroll_filtered_page(
                "chunks", query_filter=expected_filter, limit=2
            )
            last, end = self.client.scroll_filtered_page(
                "chunks", query_filter=expected_filter, limit=2, offset=cursor
            )
        finally:
            self.client._request = original
        self.assertEqual(first, [{"id": "a", "payload": {}}])
        self.assertEqual((cursor, last, end), ("b", [], None))
        self.assertEqual(RecordingHandler.requests[-2:], [
            ("POST", "/collections/chunks/points/scroll", {
                "filter": expected_filter, "limit": 2, "with_payload": True,
                "with_vector": False,
            }),
            ("POST", "/collections/chunks/points/scroll", {
                "filter": expected_filter, "limit": 2, "with_payload": True,
                "with_vector": False,
                "offset": "b",
            }),
        ])

    def test_filtered_page_refuses_missing_or_invalid_completion_cursor(self):
        original = self.client._request
        filt = {"must": [{"key": "tenant_id", "match": {"value": "a"}}]}
        for result in (
            {"points": []},
            {"points": [], "next_page_offset": False},
            {"points": [], "next_page_offset": {}},
            {"points": [], "next_page_offset": ""},
            {"points": [{}, {}], "next_page_offset": None},
        ):
            with self.subTest(result=result):
                self.client._request = lambda method, path, body: {"status": "ok", "result": result}
                with self.assertRaisesRegex(RuntimeError, "scroll"):
                    self.client.scroll_filtered_page(
                        "chunks", query_filter=filt, limit=1
                    )
        self.client._request = original

    def test_filtered_page_refuses_error_status_even_with_points(self):
        original = self.client._request
        self.client._request = lambda method, path, body: {
            "status": "error", "result": {"points": [], "next_page_offset": None},
        }
        try:
            with self.assertRaisesRegex(RuntimeError, "status"):
                self.client.scroll_filtered_page(
                    "chunks", query_filter={"must": [
                        {"key": "tenant_id", "match": {"value": "a"}},
                    ]},
                )
        finally:
            self.client._request = original

    def test_upsert_transmits_the_conditional_update_filter(self):
        guard = {"must": [{"key": "owner_id", "match": {"value": "alice"}}]}
        point = {"id": "p1", "vector": {"dense": [1.0]}, "payload": {}}
        self.client.upsert("chunks", [point], update_filter=guard)
        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual((method, path), ("PUT", "/collections/chunks/points?wait=true"))
        self.assertEqual(body, {"points": [point], "update_filter": guard})

    def test_upsert_omits_the_filter_key_when_unconditional(self):
        point = {"id": "p1", "vector": {"dense": [1.0]}, "payload": {}}
        self.client.upsert("chunks", [point])
        _, _, body = RecordingHandler.requests[-1]
        self.assertEqual(body, {"points": [point]})

    def test_upsert_rejects_an_empty_conditional_filter(self):
        point = {"id": "p1", "vector": {"dense": [1.0]}, "payload": {}}
        for invalid in ({}, [], "owner_id", 0):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "update_filter"):
                    self.client.upsert("chunks", [point], update_filter=invalid)

    def test_retrieve_points_reads_ids_with_payload_and_vectors(self):
        points = self.client.retrieve_points("chunks", ["p1", "p2"])
        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual((method, path), ("POST", "/collections/chunks/points"))
        self.assertEqual(body, {"ids": ["p1", "p2"], "with_payload": True, "with_vector": True})
        self.assertEqual(points, [])

    def test_retrieve_points_rejects_invalid_ids_and_malformed_response(self):
        for ids in ([], [""], [True], ["p1", "p1"]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.client.retrieve_points("chunks", ids)
        original = self.client._request
        self.client._request = lambda *_a, **_k: {"status": "ok", "result": {"points": []}}
        try:
            with self.assertRaisesRegex(RuntimeError, "retrieve"):
                self.client.retrieve_points("chunks", ["p1"])
        finally:
            self.client._request = original

    def test_query_sends_filter_and_does_not_default_to_unfiltered(self):
        expected_filter = {"must": [{"key": "tenant_id", "match": {"value": "a"}}]}
        self.client.query("chunks", [1.0, 0.0, 0.0, 0.0], query_filter=expected_filter, limit=5)
        _, path, body = RecordingHandler.requests[-1]
        self.assertEqual(path, "/collections/chunks/points/query")
        self.assertEqual(body["filter"], expected_filter)
        self.assertEqual(body["using"], "dense")

    def test_sparse_query_uses_named_vector_and_canonical_acl_prefilter(self):
        context = AuthorizationContext("alpha", "alice", ("admins",), 2)
        expected_filter = build_qdrant_filter(context)
        self.client.query_sparse("chunks", {"8": 0.5, "3": 0.25},
                                 context=context, limit=40)
        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual((method, path), ("POST", "/collections/chunks/points/query"))
        self.assertEqual(body, {
            "query": {"indices": [3, 8], "values": [0.25, 0.5]},
            "using": "sparse", "filter": expected_filter,
            "limit": 40, "with_payload": True,
        })

    def test_sparse_query_rejects_malformed_response_or_missing_context(self):
        context = AuthorizationContext("alpha", "alice", (), 1)
        original = self.client._request
        self.client._request = lambda *_args, **_kwargs: {"status": "error", "result": {"points": []}}
        try:
            with self.assertRaisesRegex(RuntimeError, "query status"):
                self.client.query_sparse("chunks", {"3": 0.2}, context=context)
        finally:
            self.client._request = original
        with self.assertRaisesRegex(ValueError, "context"):
            self.client.query_sparse("chunks", {"3": 0.2}, context=None)
        self.assertEqual(RecordingHandler.requests, [])

    def test_sparse_query_refuses_forged_or_malformed_context(self):
        bad_groups = AuthorizationContext("alpha", "alice", ("admins",), 2)
        object.__setattr__(bad_groups, "groups", ("admins", 1))
        bad = (None, {"must": []}, AuthorizationContext("", "alice", (), 1),
               AuthorizationContext("alpha", "alice", (), True), bad_groups)
        for context in bad:
            with self.subTest(context=context), self.assertRaisesRegex(ValueError, "context"):
                self.client.query_sparse("chunks", {"3": 0.2}, context=context)
        self.assertEqual(RecordingHandler.requests, [])

    def test_sparse_query_rejects_invalid_weights_before_network(self):
        with self.assertRaises(ValueError):
            self.client.query_sparse("chunks", {"3": float("nan")},
                                     context=AuthorizationContext("alpha", "alice", (), 1))
        self.assertEqual(RecordingHandler.requests, [])

    def test_query_rejects_missing_or_malformed_points_instead_of_abstaining(self):
        original = self.client._request
        for invalid in (None, [], {}, {"points": None}, {"points": {}}, {"points": ""}):
            with self.subTest(invalid=invalid):
                self.client._request = lambda *_args, **_kwargs: {"result": invalid}
                try:
                    with self.assertRaisesRegex(RuntimeError, "malformed query result"):
                        self.client.query(
                            "chunks", [1.0],
                            query_filter={"must": [{"has_id": ["one"]}]},
                        )
                finally:
                    self.client._request = original

    def test_query_rejects_more_points_than_requested(self):
        original = self.client._request
        self.client._request = lambda *_args, **_kwargs: {"result": {"points": [{"id": 1}, {"id": 2}]}}
        try:
            with self.assertRaisesRegex(RuntimeError, "more points than"):
                self.client.query(
                    "chunks", [1.0],
                    query_filter={"must": [{"has_id": ["one"]}]}, limit=1,
                )
        finally:
            self.client._request = original

    def test_query_rejects_missing_or_invalid_point_scores(self):
        original = self.client._request
        for score in (None, True, "0.9", float("nan"), float("inf")):
            with self.subTest(score=score):
                point = {"id": "one", "payload": {}}
                if score is not None:
                    point["score"] = score
                self.client._request = lambda *_args, **_kwargs: {"result": {"points": [point]}}
                try:
                    with self.assertRaisesRegex(RuntimeError, "invalid query score"):
                        self.client.query(
                            "chunks", [1.0], query_filter={"must": [{"has_id": ["one"]}]},
                        )
                finally:
                    self.client._request = original

    def test_query_rejects_explicit_error_status_instead_of_abstaining(self):
        original = self.client._request
        self.client._request = lambda *_args, **_kwargs: {
            "status": "error", "result": {"points": []},
        }
        try:
            with self.assertRaisesRegex(RuntimeError, "query status"):
                self.client.query(
                    "chunks", [1.0], query_filter={"must": [{"has_id": ["one"]}]},
                )
        finally:
            self.client._request = original
        self.assertEqual(self.client.query(
            "chunks", [1.0], query_filter={"must": [{"has_id": ["one"]}]},
        ), [])

    def test_query_accepts_well_formed_scored_point(self):
        original = self.client._request
        point = {"id": "one", "score": 0.9, "payload": {"document_id": "guide"}}
        self.client._request = lambda *_args, **_kwargs: {
            "status": "ok", "result": {"points": [point]},
        }
        try:
            self.assertEqual(self.client.query(
                "chunks", [1.0], query_filter={"must": [{"has_id": ["one"]}]},
            ), [point])
        finally:
            self.client._request = original

    def test_query_refuses_missing_or_empty_filter(self):
        for invalid in (None, {}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.client.query("chunks", [1.0, 0.0], query_filter=invalid)

    def test_the_read_write_client_never_exposes_unfiltered_scrolling(self):
        """Le scroll sans filtre appartient au seul lecteur d'audit
        (`tests/test_qdrant_audit_client.py`), jamais au client du service."""
        self.assertFalse(hasattr(self.client, "scroll_page"))

    def test_scroll_sends_mandatory_filter_and_returns_points(self):
        expected_filter = {
            "must": [
                {"key": "tenant_id", "match": {"value": "alpha"}},
                {"key": "document_id", "match": {"value": "guide"}},
            ]
        }
        points = self.client.scroll(
            "chunks",
            query_filter=expected_filter,
            limit=2,
        )
        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual((method, path), ("POST", "/collections/chunks/points/scroll"))
        self.assertEqual(
            body,
            {"filter": expected_filter, "limit": 2, "with_payload": True},
        )
        self.assertEqual(points, [])

    def test_scroll_refuses_missing_or_empty_filter(self):
        for invalid in (None, {}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.client.scroll("chunks", query_filter=invalid)

    def test_scroll_rejects_malformed_results(self):
        for invalid in (None, [], {}, {"points": None}, {"points": {}}):
            with self.subTest(invalid=invalid):
                original = self.client._request
                self.client._request = lambda *_args, **_kwargs: {"result": invalid}
                try:
                    with self.assertRaisesRegex(RuntimeError, "malformed"):
                        self.client.scroll(
                            "chunks",
                            query_filter={"must": [{"has_id": ["one"]}]},
                        )
                finally:
                    self.client._request = original

    def test_upsert_waits_for_payload_and_vector_persistence(self):
        point = {
            "id": "12345678-1234-5678-1234-567812345678",
            "vector": {"dense": [1.0, 0.0]},
            "payload": {"tenant_id": "a", "tombstone": False},
        }
        self.client.upsert("chunks", [point])
        _, path, body = RecordingHandler.requests[-1]
        self.assertEqual(path, "/collections/chunks/points?wait=true")
        self.assertEqual(body, {"points": [point]})

    def test_delete_points_waits_and_sends_mandatory_filter(self):
        expected_filter = {
            "must": [
                {"key": "tenant_id", "match": {"value": "alpha"}},
                {"key": "document_id", "match": {"value": "guide"}},
            ]
        }

        self.client.delete_points("chunks", expected_filter)

        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual(
            (method, path),
            ("POST", "/collections/chunks/points/delete?wait=true"),
        )
        self.assertEqual(body, {"filter": expected_filter})

    def test_delete_collection_uses_collection_endpoint(self):
        self.client.delete_collection("chunks")
        method, path, _ = RecordingHandler.requests[-1]
        self.assertEqual((method, path), ("DELETE", "/collections/chunks"))


if __name__ == "__main__":
    unittest.main()
