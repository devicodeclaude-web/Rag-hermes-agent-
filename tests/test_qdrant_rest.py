import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from rag_hermes.qdrant_rest import QdrantRestClient


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

    def test_query_refuses_missing_filter(self):
        with self.assertRaises(ValueError):
            self.client.query("chunks", [1.0, 0.0], query_filter=None)

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
