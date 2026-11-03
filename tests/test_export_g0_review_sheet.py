"""Blind review-sheet export — tests (no GPU, no network).

Validate that the sheet derived from a G0 receipt is genuinely BLIND (no case_id,
no gold label), that only concrete answers are exported, that the shuffle is
deterministic, and that the de-blinding key maps review_id -> case_id correctly.
"""
from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import export_g0_review_sheet as ex


def _canonical(report: dict) -> bytes:
    return json.dumps(
        report, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _receipt_with(records: list[dict]) -> dict:
    report = {
        "job_id": "g0-test",
        "configuration": "G0",
        "audited_commit": "0" * 40,
        "answer_records": records,
    }
    return {
        "schema_version": "gpu_execution_receipt.v2",
        "status": "completed",
        "started_utc": "2026-11-03T00:00:00Z",
        "finished_utc": "2026-11-03T00:00:01Z",
        "command": ["python", "worker.py"],
        "cwd": "/repo",
        "environment": {},
        "exit_code": 0,
        "report": report,
        "report_encoding": "canonical-json-utf8",
        "report_sha256_scope": "receipt.report canonical-json-utf8",
        "report_sha256": hashlib.sha256(_canonical(report)).hexdigest(),
    }


def _record(case_id, question, answer, did_abstain, should_abstain):
    return {
        "case_id": case_id,
        "question": question,
        "answer": answer,
        "did_abstain": did_abstain,
        "should_abstain": should_abstain,
    }


# Mix: concrete answers (did_abstain False) incl. a hallucination on a no_answer
# case, plus abstentions that must NOT appear in the review sheet.
_RECORDS = [
    _record("m001", "capital of France?", "Paris.", False, False),
    _record("m002", "unknowable private key?", "It is 1234.", False, True),
    _record("m003", "countries in Africa?", "Je ne connais pas la réponse.", True, True),
    _record("m004", "capital of Spain?", "Madrid.", False, False),
    _record("m005", "list all users?", "Je ne connais pas la réponse.", True, True),
]


class ConcreteAnswersTests(unittest.TestCase):
    def test_keeps_only_non_abstentions(self):
        answered = ex._concrete_answers({"answer_records": _RECORDS})
        self.assertEqual({r["case_id"] for r in answered}, {"m001", "m002", "m004"})

    def test_raises_when_records_absent(self):
        with self.assertRaises(ValueError):
            ex._concrete_answers({})  # legacy receipt without answer capture

    def test_raises_when_all_abstained(self):
        with self.assertRaises(ValueError):
            ex._concrete_answers(
                {"answer_records": [_record("m", "q", "Je ne connais pas la réponse.", True, True)]}
            )


class BuildBlindRowsTests(unittest.TestCase):
    def test_rows_carry_no_case_id_and_no_gold_label(self):
        answered = ex._concrete_answers({"answer_records": _RECORDS})
        rows, _ = ex.build_blind_rows(answered, "seed")
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertNotIn("case_id", row)
            self.assertNotIn("should_abstain", row)
            self.assertNotIn("did_abstain", row)
            self.assertEqual(set(row), {"review_id", "question", "model_answer", "correct", "grounded", "notes"})

    def test_key_maps_review_id_to_case_id(self):
        answered = ex._concrete_answers({"answer_records": _RECORDS})
        rows, key = ex.build_blind_rows(answered, "seed")
        self.assertEqual(set(key), {r["review_id"] for r in rows})
        self.assertEqual(set(key.values()), {"m001", "m002", "m004"})
        # the question behind a review_id matches its mapped case
        by_case = {r["case_id"]: r for r in _RECORDS}
        for row in rows:
            self.assertEqual(row["question"], by_case[key[row["review_id"]]]["question"])
            self.assertEqual(row["model_answer"], by_case[key[row["review_id"]]]["answer"])

    def test_shuffle_is_deterministic_for_a_fixed_seed(self):
        answered = ex._concrete_answers({"answer_records": _RECORDS})
        rows_a, _ = ex.build_blind_rows(answered, "seed")
        rows_b, _ = ex.build_blind_rows(answered, "seed")
        self.assertEqual([r["review_id"] for r in rows_a], [r["review_id"] for r in rows_b])
        self.assertEqual(
            [r["model_answer"] for r in rows_a], [r["model_answer"] for r in rows_b]
        )


class MainIntegrationTests(unittest.TestCase):
    def test_writes_blind_sheet_and_separate_key(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_path = tmp_path / "receipt.json"
            receipt_path.write_text(json.dumps(_receipt_with(_RECORDS)), encoding="utf-8")
            sheet = tmp_path / "sheet.csv"
            key = tmp_path / "key.json"

            import sys

            argv = sys.argv
            sys.argv = [
                "export_g0_review_sheet.py",
                "--receipt", str(receipt_path),
                "--sheet", str(sheet),
                "--key", str(key),
                "--seed", "seed",
            ]
            try:
                self.assertEqual(ex.main(), 0)
            finally:
                sys.argv = argv

            with sheet.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            sheet_text = sheet.read_text(encoding="utf-8")
            # no case_id and no gold-label column leaks into the blind sheet
            self.assertNotIn("case_id", sheet_text)
            self.assertNotIn("should_abstain", sheet_text)

            key_payload = json.loads(key.read_text(encoding="utf-8"))
            self.assertEqual(set(key_payload["review_id_to_case_id"].values()), {"m001", "m002", "m004"})
            self.assertEqual(key_payload["blind_count"], 3)
            self.assertEqual(
                key_payload["source_receipt_sha256"],
                hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
