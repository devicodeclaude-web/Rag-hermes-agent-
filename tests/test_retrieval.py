import unittest

from rag_hermes.acl import AuthorizationContext, Chunk
from rag_hermes.retrieval import LexicalRetriever


def make_chunk(chunk_id: str, tenant: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=chunk_id,
        text=text,
        tenant_id=tenant,
        visibility="private",
        allowed_groups=("users",),
        allowed_users=(),
        owner_id="owner",
        classification=1,
        doc_version=1,
        source_sha=(chunk_id[0] if chunk_id[0] in "abcdef" else "a") * 64,
    )


class RetrievalTests(unittest.TestCase):
    def test_exactly_matching_foreign_secret_is_never_returned(self):
        retriever = LexicalRetriever(
            [
                make_chunk("a-public", "tenant-a", "installer Hermes sous Termux"),
                make_chunk("b-secret", "tenant-b", "ultrasecretterm ultrasecretterm"),
            ]
        )
        context = AuthorizationContext("tenant-a", "alice", ("users",), 1)
        results = retriever.search("ultrasecretterm", context=context, limit=10)
        self.assertEqual(results, [])

    def test_results_are_ranked_by_bm25_score(self):
        retriever = LexicalRetriever(
            [
                make_chunk("a-one", "tenant-a", "installer Hermes sous Linux"),
                make_chunk("b-two", "tenant-a", "installer configurer Hermes sous Termux"),
            ]
        )
        context = AuthorizationContext("tenant-a", "alice", ("users",), 1)
        results = retriever.search(
            "installer configurer Hermes", context=context, limit=2
        )
        self.assertEqual([result.chunk.chunk_id for result in results], ["b-two", "a-one"])
        self.assertGreater(results[0].score, results[1].score)

    def test_rare_discriminative_term_outranks_repeated_common_term(self):
        retriever = LexicalRetriever(
            [
                make_chunk("a-common", "tenant-a", "common common common filler"),
                make_chunk("b-rare", "tenant-a", "common rare"),
                make_chunk("c-background", "tenant-a", "common background"),
            ]
        )
        context = AuthorizationContext("tenant-a", "alice", ("users",), 1)
        results = retriever.search("common common rare", context=context, limit=2)
        self.assertEqual(results[0].chunk.chunk_id, "b-rare")

    def test_bm25_rank_order_keeps_public_scores_monotonic(self):
        retriever = LexicalRetriever(
            [
                make_chunk("a-common", "tenant-a", "common common common filler"),
                make_chunk("b-rare", "tenant-a", "common rare"),
                make_chunk("c-background", "tenant-a", "common background"),
            ]
        )
        context = AuthorizationContext("tenant-a", "alice", ("users",), 1)
        results = retriever.search("common common common rare", context=context, limit=3)
        self.assertEqual(results[0].chunk.chunk_id, "b-rare")
        self.assertEqual(
            [result.score for result in results],
            sorted((result.score for result in results), reverse=True),
        )

    def test_query_without_matching_terms_returns_no_results(self):
        retriever = LexicalRetriever(
            [make_chunk("a-one", "tenant-a", "installation Hermes")]
        )
        context = AuthorizationContext("tenant-a", "alice", ("users",), 1)
        self.assertEqual(retriever.search("recette cuisine", context=context), [])


if __name__ == "__main__":
    unittest.main()
