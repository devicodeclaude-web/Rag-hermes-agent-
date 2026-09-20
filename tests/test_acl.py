import unittest

from rag_hermes.acl import AuthorizationContext, Chunk, filter_authorized


class ACLTests(unittest.TestCase):
    def setUp(self):
        self.public = Chunk(
            chunk_id="public-1",
            document_id="doc-public",
            text="Documentation publique Hermes Agent.",
            tenant_id="tenant-a",
            visibility="public",
            allowed_groups=(),
            allowed_users=(),
            owner_id="docs-team",
            classification=0,
            doc_version=1,
            source_sha="a" * 64,
        )
        self.private = Chunk(
            chunk_id="private-1",
            document_id="doc-private",
            text="Convention privée du vault Jarvis.",
            tenant_id="tenant-a",
            visibility="private",
            allowed_groups=("admins",),
            allowed_users=(),
            owner_id="alice",
            classification=2,
            doc_version=3,
            source_sha="b" * 64,
        )

    def test_retrieval_requires_authorization_context(self):
        with self.assertRaises(ValueError):
            filter_authorized([self.public], None)

    def test_cross_tenant_chunks_are_rejected(self):
        context = AuthorizationContext(
            tenant_id="tenant-b", user_id="bob", groups=("admins",), clearance=5
        )
        self.assertEqual(filter_authorized([self.public, self.private], context), [])

    def test_global_public_chunk_is_visible_to_each_tenant(self):
        global_public = Chunk(
            chunk_id="global-1",
            document_id="hermes-docs",
            text="Documentation Hermes Agent.",
            tenant_id="public",
            visibility="public",
            allowed_groups=(),
            allowed_users=(),
            owner_id="nousresearch",
            classification=0,
            doc_version=1,
            source_sha="c" * 64,
        )
        context = AuthorizationContext(
            tenant_id="tenant-b", user_id="bob", groups=(), clearance=0
        )
        self.assertEqual(filter_authorized([global_public], context), [global_public])

    def test_group_and_clearance_are_both_required_for_private_chunk(self):
        insufficient = AuthorizationContext(
            tenant_id="tenant-a", user_id="bob", groups=("admins",), clearance=1
        )
        authorized = AuthorizationContext(
            tenant_id="tenant-a", user_id="bob", groups=("admins",), clearance=2
        )
        self.assertEqual(filter_authorized([self.private], insufficient), [])
        self.assertEqual(filter_authorized([self.private], authorized), [self.private])

    def test_owner_can_read_private_chunk_with_sufficient_clearance(self):
        context = AuthorizationContext(
            tenant_id="tenant-a", user_id="alice", groups=(), clearance=2
        )
        self.assertEqual(filter_authorized([self.private], context), [self.private])

    def test_source_sha_must_be_sha256_hex(self):
        with self.assertRaises(ValueError):
            Chunk(
                chunk_id="bad",
                document_id="bad",
                text="bad",
                tenant_id="tenant-a",
                visibility="public",
                allowed_groups=(),
                allowed_users=(),
                owner_id="alice",
                classification=0,
                doc_version=1,
                source_sha="not-a-sha",
            )


if __name__ == "__main__":
    unittest.main()
