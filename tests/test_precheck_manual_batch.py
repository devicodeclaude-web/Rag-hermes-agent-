from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import scripts.precheck_manual_batch as pc
from rag_hermes.eval_corpus import DEFAULT_CORPUS, corpus_manifest, load_documents


class CheckBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = load_documents(DEFAULT_CORPUS)
        cls.manifest = corpus_manifest(DEFAULT_CORPUS)
        # Pick a real document and a verbatim, unique passage from it so that a
        # well-formed row genuinely validates against the canonical corpus.
        cls.doc_id = next(iter(cls.documents))
        content = str(cls.documents[cls.doc_id]["content"])
        # A short slice that is (very likely) unique; extend until unique.
        n = 60
        while True:
            passage = content[:n]
            if content.find(passage, content.find(passage) + 1) == -1:
                break
            n += 20
            if n > len(content):
                break
        cls.passage = passage

    def _good_row(self, case_id="m-good-en", **over):
        row = {
            "case_id": case_id,
            "question": "A genuine human question about Hermes.",
            "language": "en",
            "track": "en2en",
            "category": "simple",
            "access_scope": "public",
            "question_provenance": "human_task_without_corpus_view",
            "should_abstain": False,
            "unanswerable_reason": None,
            "reference_status": "pending",
            "relevant_passages": [
                {"document_id": self.doc_id, "passage_text": self.passage,
                 "relevance_grade": 2}
            ],
        }
        row.update(over)
        return row

    def test_clean_batch_reports_no_problems(self):
        rows = [self._good_row("m-clean-en")]
        problems = pc.check_batch(rows, self.documents, self.manifest, existing_ids=set())
        self.assertEqual(problems, [])

    def test_aggregates_all_problems_not_just_the_first(self):
        # Row 0: unresolved REMPLIR placeholder. Row 1: lang/track mismatch.
        # Row 2: unknown document_id. A first-error-only checker would hide 1 and 2.
        rows = [
            self._good_row("m-a-en", question="REMPLIR_QUESTION_EN"),
            self._good_row("m-b-en", language="fr"),  # fr with track en2en
            self._good_row(
                "m-c-en",
                relevant_passages=[{"document_id": "does:not/exist.md",
                                    "passage_text": "x", "relevance_grade": 2}],
            ),
        ]
        problems = pc.check_batch(rows, self.documents, self.manifest, existing_ids=set())
        indexes = {p["index"] for p in problems}
        self.assertEqual(indexes, {0, 1, 2})  # every bad row is reported

    def test_flags_unresolved_placeholder_tokens(self):
        rows = [self._good_row("m-ph-en", question="REMPLIR_QUESTION_EN")]
        problems = pc.check_batch(rows, self.documents, self.manifest, existing_ids=set())
        self.assertEqual(len(problems), 1)
        self.assertIn("placeholder", problems[0]["message"].lower())

    def test_flags_duplicate_case_id_within_batch(self):
        rows = [self._good_row("m-dup-en"), self._good_row("m-dup-en")]
        problems = pc.check_batch(rows, self.documents, self.manifest, existing_ids=set())
        msgs = " ".join(p["message"].lower() for p in problems)
        self.assertIn("duplicate", msgs)

    def test_flags_case_id_already_in_dataset(self):
        rows = [self._good_row("m-existing-en")]
        problems = pc.check_batch(
            rows, self.documents, self.manifest, existing_ids={"m-existing-en"})
        self.assertTrue(any("already" in p["message"].lower() for p in problems))

    def test_check_batch_never_writes_dataset(self):
        before = pc.DATASET.exists()
        rows = [self._good_row("m-nowrite-en")]
        pc.check_batch(rows, self.documents, self.manifest, existing_ids=set())
        self.assertEqual(pc.DATASET.exists(), before)

    def test_check_batch_leaves_existing_dataset_byte_identical(self):
        # Strong innocuousness: when a dataset already exists, its exact bytes and
        # mtime must be untouched after a check (not merely "still exists").
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "dataset-v2.jsonl"
            payload = (json.dumps(self._good_row("m-pre-en"), ensure_ascii=False)
                       + "\n").encode("utf-8")
            fake.write_bytes(payload)
            before_sha = hashlib.sha256(fake.read_bytes()).hexdigest()
            before_mtime = fake.stat().st_mtime_ns
            orig = pc.DATASET
            try:
                pc.DATASET = fake  # point the module's dataset at the sandbox
                rows = [self._good_row("m-new-en")]
                pc.check_batch(rows, self.documents, self.manifest,
                               existing_ids=pc._existing_ids())
            finally:
                pc.DATASET = orig
            self.assertEqual(hashlib.sha256(fake.read_bytes()).hexdigest(), before_sha)
            self.assertEqual(fake.stat().st_mtime_ns, before_mtime)

    def test_empty_batch_is_a_problem_aligned_with_ingest(self):
        # ingest_manual_batch refuses an empty batch (exit 1). precheck must NOT
        # declare an empty batch READY_TO_INGEST; it is a problem (exit 2).
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / "empty.jsonl"
            empty.write_text("", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = pc.run(empty)
            self.assertEqual(rc, 2)
            self.assertIn("empty", buf.getvalue().lower())

    def test_typeerror_is_captured_not_raised(self):
        # A row whose relevant_passages is the wrong type triggers a TypeError
        # deep in build_case; precheck must report it, never propagate it.
        rows = [self._good_row("m-type-en", relevant_passages="not-a-list")]
        problems = pc.check_batch(rows, self.documents, self.manifest,
                                  existing_ids=set())
        self.assertTrue(problems)  # reported, no exception escaped

    def test_cli_exit_zero_on_clean_and_two_on_problems(self, ):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            clean = Path(d) / "clean.jsonl"
            clean.write_text(
                json.dumps(self._good_row("m-cli-en"), ensure_ascii=False) + "\n",
                encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = pc.run(clean)
            self.assertEqual(rc, 0)

            bad = Path(d) / "bad.jsonl"
            bad.write_text(
                json.dumps(self._good_row("m-cli2-en", question="REMPLIR_X"),
                           ensure_ascii=False) + "\n",
                encoding="utf-8")
            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                rc2 = pc.run(bad)
            self.assertEqual(rc2, 2)


if __name__ == "__main__":
    unittest.main()
