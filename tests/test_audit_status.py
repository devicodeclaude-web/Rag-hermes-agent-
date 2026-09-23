import tempfile
import unittest
from pathlib import Path

from rag_hermes.audit_status import derive_lot_statuses


HEADER = "audited_commit: abc\nexit_code: {code}\n"


class AuditStatusTests(unittest.TestCase):
    def test_failed_commands_are_preserved_and_reflected_as_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs = root / "preuves"
            history = root / "historique"
            proofs.mkdir()
            history.mkdir()
            (proofs / "tests-ci-strict.txt").write_text(HEADER.format(code=0))
            (proofs / "lock-install.txt").write_text(HEADER.format(code=1))
            (proofs / "runtime-identity.txt").write_text(HEADER.format(code=0))
            (proofs / "dataset-v1-validation.txt").write_text(HEADER.format(code=2))
            (proofs / "acl-matrix-qdrant.txt").write_text(HEADER.format(code=0))

            statuses = derive_lot_statuses(proofs, history)

            self.assertEqual(statuses["lot_1"]["status"], "BLOQUÉ")
            self.assertEqual(statuses["lot_3"]["status"], "BLOQUÉ")
            self.assertEqual(statuses["lot_4"]["status"], "FERMÉ")
            self.assertEqual(statuses["lot_1"]["exit_codes"]["lock-install.txt"], 1)

    def test_missing_evidence_never_closes_a_lot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs = root / "preuves"
            history = root / "historique"
            proofs.mkdir()
            history.mkdir()
            statuses = derive_lot_statuses(proofs, history)
            self.assertTrue(all(item["status"] != "FERMÉ" for item in statuses.values()))


if __name__ == "__main__":
    unittest.main()
