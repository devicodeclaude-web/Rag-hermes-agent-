import hashlib
import unittest

from rag_hermes.ingestion import Document, chunk_document


class IngestionTests(unittest.TestCase):
    def test_chunks_preserve_acl_version_and_source_hash(self):
        content = " ".join(f"token-{i}" for i in range(37))
        document = Document(
            document_id="private-guide",
            content=content,
            tenant_id="tenant-a",
            visibility="private",
            owner_id="alice",
            allowed_groups=("operators",),
            allowed_users=(),
            classification=2,
            doc_version=4,
            source_uri="vault://jarvis/private-guide.md",
        )
        chunks = chunk_document(document, max_tokens=10, overlap_tokens=2)
        self.assertGreater(len(chunks), 1)
        expected_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.assertTrue(all(chunk.source_sha == expected_sha for chunk in chunks))
        self.assertTrue(all(chunk.doc_version == 4 for chunk in chunks))
        self.assertTrue(all(chunk.allowed_groups == ("operators",) for chunk in chunks))
        self.assertTrue(
            all(chunk.source_uri == "vault://jarvis/private-guide.md" for chunk in chunks)
        )
        self.assertTrue(all(len(chunk.text.split()) <= 10 for chunk in chunks))
        self.assertEqual(len({chunk.chunk_id for chunk in chunks}), len(chunks))

    def test_invalid_overlap_is_rejected(self):
        document = Document(
            document_id="doc",
            content="one two",
            tenant_id="tenant-a",
            visibility="public",
            owner_id="docs",
            allowed_groups=(),
            allowed_users=(),
            classification=0,
            doc_version=1,
            source_uri="git://docs/doc.md",
        )
        with self.assertRaises(ValueError):
            chunk_document(document, max_tokens=10, overlap_tokens=10)


if __name__ == "__main__":
    unittest.main()
