import unittest
from pathlib import Path

from rag_hermes.gpu_job import load_gpu_job


class GPUJobTests(unittest.TestCase):
    def test_candidate_job_validates_locks_and_resource_contract(self):
        plan = load_gpu_job(Path("manifests/gpu/bge-m3-smoke-rtx4090.json"))
        self.assertEqual(plan.job_id, "bge-m3-smoke-rtx4090-v1")
        self.assertEqual(plan.gpu_model, "NVIDIA GeForce RTX 4090")
        self.assertEqual(plan.dense_dimension, 1024)
        self.assertEqual(plan.reranker_max_length, 512)
        self.assertEqual(plan.question_max_tokens, 96)
        self.assertEqual(plan.passage_max_tokens, 384)
        self.assertEqual(plan.overlap_tokens, 64)
        self.assertLessEqual(
            plan.question_max_tokens + plan.passage_max_tokens + plan.special_token_reserve,
            plan.reranker_max_length,
        )
        self.assertGreater(plan.required_model_bytes, 4_000_000_000)

    def test_reranker_truncation_policy_must_be_reject(self):
        manifest = Path("manifests/gpu/bge-m3-smoke-rtx4090.json")
        import json
        import tempfile

        data = json.loads(manifest.read_text())
        data["reranker"]["truncation_policy"] = "truncate"
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.json"
            bad.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_gpu_job(bad)


if __name__ == "__main__":
    unittest.main()
