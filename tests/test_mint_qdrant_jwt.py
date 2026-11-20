from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

import scripts.mint_qdrant_jwt as mint
from rag_hermes.qdrant_identity import collection_access_claims, validate_service_tokens

SECRET = "operator-service-api-key"


class MintQdrantJwtScriptTests(unittest.TestCase):
    def run_script(self, argv, env):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(mint.sys, "stdout", stdout),
            patch.object(mint.sys, "stderr", stderr),
        ):
            code = mint.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_prints_a_pair_the_service_accepts(self):
        code, out, err = self.run_script(
            ["--collection", "hermes_chunks_v1", "--ttl-days", "1"],
            {mint.SECRET_ENV: SECRET},
        )
        self.assertEqual(code, 0)
        pairs = dict(line.split("=", 1) for line in out.strip().splitlines())
        self.assertEqual(
            sorted(pairs), ["RAG_QDRANT_QUERY_API_KEY", "RAG_QDRANT_WRITE_API_KEY"]
        )
        validate_service_tokens(
            query_key=pairs["RAG_QDRANT_QUERY_API_KEY"],
            write_key=pairs["RAG_QDRANT_WRITE_API_KEY"],
            collection="hermes_chunks_v1",
        )
        self.assertEqual(
            collection_access_claims(pairs["RAG_QDRANT_QUERY_API_KEY"]),
            (("hermes_chunks_v1", "r"),),
        )
        self.assertEqual(
            collection_access_claims(pairs["RAG_QDRANT_WRITE_API_KEY"]),
            (("hermes_chunks_v1", "prw"),),
        )
        self.assertNotIn(SECRET, out)
        self.assertNotIn(SECRET, err)

    def test_refuses_to_run_without_the_signing_secret(self):
        code, out, err = self.run_script(["--collection", "c"], {})
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn(mint.SECRET_ENV, err)

    def test_refuses_a_non_positive_lifetime(self):
        code, out, _ = self.run_script(
            ["--ttl-days", "0"], {mint.SECRET_ENV: SECRET}
        )
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_can_mint_one_identity_at_a_time(self):
        code, out, _ = self.run_script(
            ["--only", "prw"], {mint.SECRET_ENV: SECRET}
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertTrue(out.startswith("RAG_QDRANT_WRITE_API_KEY="))


if __name__ == "__main__":
    unittest.main()
