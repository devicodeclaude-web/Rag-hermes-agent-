import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from rag_hermes.acl import AuthorizationContext
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_rest import QdrantAuditRestClient, QdrantRestClient


class RecordingHandler(BaseHTTPRequestHandler):
    requests = []
    exists_result: Any = True

    def log_message(self, format, *args):
        return

    def _record(self):
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.requests.append((self.command, self.path, body))
        result = (
            {"exists": self.__class__.exists_result}
            if self.path.endswith("/exists")
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
        RecordingHandler.exists_result = True
        self.client = QdrantRestClient(self.base_url)

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

    def test_unfiltered_audit_scroll_page_uses_cursor_without_changing_filtered_scroll(self):
        self.assertFalse(hasattr(self.client, "scroll_page"))
        audit_client = QdrantAuditRestClient(self.base_url)
        original = audit_client._request
        calls = []
        def request(method, path, body):
            calls.append((method, path, body))
            return {"result": {"points": [{"id": "one", "payload": {}}],
                               "next_page_offset": "next-id"}}
        audit_client._request = request
        try:
            points, cursor = audit_client.scroll_page("chunks", limit=3, offset="start-id")
        finally:
            audit_client._request = original
        self.assertEqual(points, [{"id": "one", "payload": {}}])
        self.assertEqual(cursor, "next-id")
        self.assertEqual(calls, [("POST", "/collections/chunks/points/scroll", {
            "limit": 3, "offset": "start-id", "with_payload": True,
            "with_vector": False,
        })])

    def test_audit_scroll_page_rejects_malformed_results(self):
        audit_client = QdrantAuditRestClient(self.base_url)
        original = audit_client._request
        for invalid in (
            None, [], {}, {"points": None}, {"points": {}},
            {"points": []},
            {"points": [], "next_page_offset": []},
            {"points": [], "next_page_offset": {}},
            {"points": [], "next_page_offset": 1.5},
            {"points": [], "next_page_offset": True},
        ):
            with self.subTest(invalid=invalid):
                audit_client._request = lambda *_a, **_k: {"result": invalid}
                try:
                    with self.assertRaisesRegex(RuntimeError, "malformed"):
                        audit_client.scroll_page("chunks", limit=2)
                finally:
                    audit_client._request = original

    def test_audit_scroll_page_rejects_self_referential_cursor(self):
        audit_client = QdrantAuditRestClient(self.base_url)
        original = audit_client._request
        audit_client._request = lambda *_a, **_k: {"result": {
            "points": [{"id": "a"}], "next_page_offset": "same-id",
        }}
        try:
            with self.assertRaisesRegex(RuntimeError, "cursor"):
                audit_client.scroll_page("chunks", limit=1, offset="same-id")
        finally:
            audit_client._request = original

    def test_audit_scroll_page_rejects_oversized_page(self):
        audit_client = QdrantAuditRestClient(self.base_url)
        original = audit_client._request
        audit_client._request = lambda *_a, **_k: {"result": {
            "points": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "next_page_offset": None,
        }}
        try:
            with self.assertRaisesRegex(RuntimeError, "more points than"):
                audit_client.scroll_page("chunks", limit=2)
        finally:
            audit_client._request = original

    def test_audit_scroll_page_refuses_invalid_limit_or_offset(self):
        audit_client = QdrantAuditRestClient(self.base_url)
        for limit in (0, -1, 1001):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(ValueError, "bounded scroll limit"):
                    audit_client.scroll_page("chunks", limit=limit)
        for offset in (1.5, True, [], {}):
            with self.subTest(offset=offset):
                with self.assertRaisesRegex(ValueError, "invalid scroll offset"):
                    audit_client.scroll_page("chunks", limit=2, offset=offset)

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
