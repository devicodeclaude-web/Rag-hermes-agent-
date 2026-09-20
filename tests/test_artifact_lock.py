import json
import unittest
from pathlib import Path

from rag_hermes.artifact_lock import validate_artifact_lock


class ArtifactLockTests(unittest.TestCase):
    def test_bge_locks_recompute_to_declared_bundle_hash(self):
        for path in (
            Path("manifests/locks/bge-m3.lock.json"),
            Path("manifests/locks/bge-reranker-v2-m3.lock.json"),
        ):
            lock = json.loads(path.read_text())
            self.assertEqual(validate_artifact_lock(lock), lock["bundle_sha256"])

    def test_mutated_file_hash_is_rejected(self):
        lock = json.loads(Path("manifests/locks/bge-m3.lock.json").read_text())
        lock["files"][0]["git_oid"] = "0" * 40
        with self.assertRaises(ValueError):
            validate_artifact_lock(lock)


if __name__ == "__main__":
    unittest.main()
