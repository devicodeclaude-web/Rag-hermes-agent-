from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.provision_qdrant import main, parse_args


class ProvisionQdrantCliTests(unittest.TestCase):
    def test_defaults_match_service_and_pinned_bge_m3(self) -> None:
        args = parse_args([])
        self.assertEqual(args.url, "http://127.0.0.1:6333")
        self.assertEqual(args.collection, "hermes_chunks_v1")
        self.assertEqual(args.vector_size, 1024)
        self.assertEqual(args.index_spec, "qdrant/payload-indexes.json")
        specification = json.loads(
            Path(args.index_spec).read_text(encoding="utf-8")
        )
        self.assertEqual(specification["collection"], args.collection)

    @patch("scripts.provision_qdrant.provision_collection")
    @patch("scripts.provision_qdrant.QdrantRestClient")
    def test_main_provisions_and_prints_machine_readable_report(
        self, client_type, provision
    ) -> None:
        client = client_type.return_value
        provision.return_value = {
            "collection": "custom",
            "collection_created": True,
            "indexes_created": ["tenant_id"],
            "ready": True,
        }
        output = io.StringIO()

        with redirect_stdout(output):
            result = main(
                [
                    "--url",
                    "http://127.0.0.1:6402",
                    "--collection",
                    "custom",
                    "--vector-size",
                    "4",
                ]
            )

        self.assertEqual(result, 0)
        client_type.assert_called_once_with("http://127.0.0.1:6402", timeout=120)
        _, kwargs = provision.call_args
        self.assertIs(kwargs["client"], client)
        self.assertEqual(kwargs["collection"], "custom")
        self.assertEqual(kwargs["vector_size"], 4)
        self.assertEqual(len(kwargs["specification"]["payload_indexes"]), 11)
        self.assertEqual(json.loads(output.getvalue()), provision.return_value)


if __name__ == "__main__":
    unittest.main()
