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

    def test_zero_width_window_is_skipped_instead_of_poisoning_the_document(self):
        class DroppingTokenizer:
            """Emits a trailing window whose tokens have zero-width offsets."""

            def __call__(self, text, **kwargs):
                return {
                    "input_ids": [1, 2, 3, 4],
                    "offset_mapping": [(0, 4), (5, 9), (9, 9), (9, 9)],
                }

        document = Document(
            document_id="doc-z",
            content="tok0 tok1",
            tenant_id="alpha",
            visibility="private",
            owner_id="alice",
            allowed_groups=(),
            allowed_users=(),
            classification=1,
            doc_version=1,
            source_uri="synthetic://alpha/doc-z",
        )
        chunks = chunk_document_tokens(
            document, DroppingTokenizer(), max_passage_tokens=2, overlap_tokens=0,
            tokenizer_name="dropping", tokenizer_revision="test",
        )
        # The empty window carries no document bytes: emitting it would make
        # the whole document unindexable (no provenance check can accept it).
        self.assertEqual(
            [(chunk.start_offset, chunk.end_offset) for chunk in chunks],
            [(0, 9)],
        )
        for chunk in chunks:
            self.assertEqual(
                chunk.text, document.content[chunk.start_offset:chunk.end_offset]
            )

    def test_all_zero_width_windows_fail_loudly_instead_of_emptying_the_document(self):
        class DegenerateTokenizer:
            def __call__(self, text, **kwargs):
                return {"input_ids": [1, 2], "offset_mapping": [(0, 0), (0, 0)]}

        # Returning zero chunk would let replace_document delete the previous
        # revision and report success on an emptied document.
        with self.assertRaisesRegex(ValueError, "no indexable passage"):
            chunk_document_tokens(
                self.document, DegenerateTokenizer(), max_passage_tokens=2,
                overlap_tokens=0, tokenizer_name="degenerate",
                tokenizer_revision="test",
            )

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
