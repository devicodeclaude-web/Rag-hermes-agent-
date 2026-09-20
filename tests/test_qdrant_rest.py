import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rag_hermes.qdrant_rest import QdrantRestClient


class RecordingHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, format, *args):
        return

    def _record(self):
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.requests.append((self.command, self.path, body))
        response = {"result": {"points": []}, "status": "ok", "time": 0.0}
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    do_PUT = _record
    do_POST = _record
    do_DELETE = _record


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
        self.client = QdrantRestClient(self.base_url)

    def test_create_collection_sends_named_dense_vector_config(self):
        self.client.create_collection("chunks", vector_size=4)
        method, path, body = RecordingHandler.requests[-1]
        self.assertEqual((method, path), ("PUT", "/collections/chunks"))
        self.assertEqual(body["vectors"], {"dense": {"size": 4, "distance": "Cosine"}})

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

    def test_delete_collection_uses_collection_endpoint(self):
        self.client.delete_collection("chunks")
        method, path, _ = RecordingHandler.requests[-1]
        self.assertEqual((method, path), ("DELETE", "/collections/chunks"))


if __name__ == "__main__":
    unittest.main()
