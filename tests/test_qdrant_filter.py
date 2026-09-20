import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.qdrant_filter import build_qdrant_filter


class QdrantFilterTests(unittest.TestCase):
    def test_filter_contains_tenant_clearance_and_global_public_branch(self):
        context = AuthorizationContext("tenant-a", "alice", ("admins", "ops"), 2)
        payload_filter = build_qdrant_filter(context)
        serialized = repr(payload_filter)
        self.assertIn("tenant-a", serialized)
        self.assertIn("public", serialized)
        self.assertIn("alice", serialized)
        self.assertIn("admins", serialized)
        self.assertIn("ops", serialized)
        self.assertIn("classification", serialized)
        self.assertIn("tombstone", serialized)

    def test_filter_never_accepts_missing_context(self):
        with self.assertRaises(ValueError):
            build_qdrant_filter(None)


if __name__ == "__main__":
    unittest.main()
