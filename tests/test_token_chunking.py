import unittest

from rag_hermes.ingestion import Document, chunk_document_tokens


class WhitespaceOffsetTokenizer:
    """Tokenizer déterministe de test avec offsets de caractères."""

    def __call__(self, text, **kwargs):
        self.last_kwargs = kwargs
        offsets = []
        input_ids = []
        cursor = 0
        for index, word in enumerate(text.split()):
            start = text.index(word, cursor)
            end = start + len(word)
            offsets.append((start, end))
            input_ids.append(index + 1)
            cursor = end
        return {"input_ids": input_ids, "offset_mapping": offsets}


class TokenChunkingTests(unittest.TestCase):
    def setUp(self):
        self.document = Document(
            document_id="doc-1",
            content=" ".join(f"tok{i}" for i in range(900)),
            tenant_id="alpha",
            visibility="private",
            owner_id="alice",
            allowed_groups=("admins",),
            allowed_users=(),
            classification=2,
            doc_version=1,
            source_uri="synthetic://alpha/doc-1",
        )
        self.tokenizer = WhitespaceOffsetTokenizer()

    def test_chunks_are_bounded_by_exact_token_budget(self):
        chunks = chunk_document_tokens(
            self.document,
            self.tokenizer,
            max_passage_tokens=384,
            overlap_tokens=64,
            tokenizer_name="BAAI/bge-reranker-v2-m3",
            tokenizer_revision="953dc6f",
        )

        self.assertEqual([chunk.token_count for chunk in chunks], [384, 384, 260])
        self.assertTrue(all(chunk.token_count <= 384 for chunk in chunks))
        self.assertEqual(chunks[0].text.split()[320:], chunks[1].text.split()[:64])
        self.assertFalse(self.tokenizer.last_kwargs["add_special_tokens"])
        self.assertFalse(self.tokenizer.last_kwargs["truncation"])
        self.assertTrue(self.tokenizer.last_kwargs["return_offsets_mapping"])

    def test_chunks_record_offsets_tokenizer_and_content_hash(self):
        chunks = chunk_document_tokens(
            self.document,
            self.tokenizer,
            max_passage_tokens=384,
            overlap_tokens=64,
            tokenizer_name="BAAI/bge-reranker-v2-m3",
            tokenizer_revision="953dc6f",
        )

        first = chunks[0]
        self.assertEqual(first.start_offset, 0)
        self.assertEqual(first.end_offset, len(first.text))
        self.assertEqual(first.tokenizer_name, "BAAI/bge-reranker-v2-m3")
        self.assertEqual(first.tokenizer_revision, "953dc6f")
        self.assertEqual(first.content_hash, first.source_sha)

    def test_invalid_token_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            chunk_document_tokens(
                self.document,
                self.tokenizer,
                max_passage_tokens=64,
                overlap_tokens=64,
                tokenizer_name="tokenizer",
                tokenizer_revision="revision",
            )


if __name__ == "__main__":
    unittest.main()
