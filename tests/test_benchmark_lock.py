import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "manifests/locks/benchmark-v2.lock.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _records(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class BenchmarkLockTests(unittest.TestCase):
    """Grave l'identité figée du benchmark v2 : toute dérive casse la CI."""

    @classmethod
    def setUpClass(cls):
        cls.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        cls.entries = [cls.lock["active_dataset"], *cls.lock["strata"], *cls.lock["fixture_dependencies"]]

    def test_each_pinned_file_matches_sha_and_count(self):
        for entry in self.entries:
            path = ROOT / entry["path"]
            with self.subTest(path=entry["path"]):
                self.assertTrue(path.exists(), f"fichier figé absent: {entry['path']}")
                self.assertEqual(_sha256(path), entry["sha256"], f"sha256 dérivé: {entry['path']}")
                self.assertEqual(len(_records(path)), entry["record_count"], f"compte dérivé: {entry['path']}")

    def test_aggregate_benchmark_sha_matches(self):
        parts = {e["path"]: _sha256(ROOT / e["path"]) for e in self.entries}
        agg = "\n".join(f"{p}:{parts[p]}" for p in sorted(parts))
        self.assertEqual(hashlib.sha256(agg.encode("utf-8")).hexdigest(), self.lock["benchmark_sha"])

    def test_active_set_is_public_only(self):
        active = ROOT / self.lock["active_dataset"]["path"]
        acl_flags = {bool(r.get("acl_probe", False)) for r in _records(active)}
        self.assertEqual(acl_flags, {False}, "le jeu actif doit rester public-only (acl_probe False partout)")

    def test_category_distribution_sums_to_record_count(self):
        dist = self.lock["active_dataset"]["category_distribution"]
        self.assertEqual(sum(dist.values()), self.lock["active_dataset"]["record_count"])

    def test_human_independent_review_not_overclaimed(self):
        # Honnêteté : le gel ne doit jamais prétendre une revue humaine indépendante.
        self.assertEqual(self.lock["review_status"]["human_independent_review"], "NON ATTEINT")


if __name__ == "__main__":
    unittest.main()
