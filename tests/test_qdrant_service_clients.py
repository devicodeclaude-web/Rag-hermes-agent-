from unittest import TestCase
from unittest.mock import Mock

from rag_hermes.qdrant_service_clients import QdrantRepositoryClients


class QdrantRepositoryClientsTests(TestCase):
    def test_explicit_routing_keeps_queries_off_the_writer(self):
        reader = Mock()
        writer = Mock()
        adapter = QdrantRepositoryClients(reader, writer)
        adapter.query("chunks", [0.1], query_filter={"must": [1]}, limit=2)
        adapter.query_sparse("chunks", {"1": 0.5}, context=object(), limit=2)
        reader.query.assert_called_once()
        reader.query_sparse.assert_called_once()
        writer.query.assert_not_called()
        writer.query_sparse.assert_not_called()

    def test_write_lifecycle_uses_writer_and_exposes_no_admin_methods(self):
        reader = Mock()
        writer = Mock()
        adapter = QdrantRepositoryClients(reader, writer)
        adapter.scroll_filtered_page("chunks", query_filter={"must": [1]}, limit=1)
        adapter.upsert("chunks", [{"id": "one"}], update_filter={"must": [1]})
        adapter.retrieve_points("chunks", ["one"])
        adapter.delete_points("chunks", {"must": [1]})
        for name in ("scroll_filtered_page", "upsert", "retrieve_points", "delete_points"):
            getattr(writer, name).assert_called_once()
            getattr(reader, name).assert_not_called()
        for name in ("create_collection", "delete_collection", "create_payload_index", "scroll_page"):
            self.assertFalse(hasattr(adapter, name), name)

    def test_collection_metadata_is_read_with_the_read_identity(self):
        reader = Mock()
        writer = Mock()
        adapter = QdrantRepositoryClients(reader, writer)
        adapter.get_collection("chunks")
        reader.get_collection.assert_called_once_with("chunks")
        writer.get_collection.assert_not_called()

    def test_the_same_client_cannot_serve_both_identities(self):
        client = Mock()
        with self.assertRaisesRegex(ValueError, "distinct"):
            QdrantRepositoryClients(client, client)
