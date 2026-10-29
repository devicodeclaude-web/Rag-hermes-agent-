import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from rag_hermes.abstention_calibration import (
    deterministic_group_split,
    human_cases_to_questions,
)
from rag_hermes.eval_corpus import corpus_manifest, load_documents
from rag_hermes.gpu_job import load_gpu_job
from scripts import run_bge_gpu_campaign as campaign


class GPUJobTests(unittest.TestCase):
    def test_runbook_requires_preprovisioning_gates_before_pod_creation(self):
        runbook = Path("docs/smoke-gpu-runbook.md").read_text(encoding="utf-8")

        self.assertIn("portes 0 à 3 ne sont pas vertes", runbook)
        self.assertNotIn("portes 1 à 4 ne sont pas vertes", runbook)

    def test_runbook_does_not_conflate_active_298_with_final_quality_track(self):
        active = [
            json.loads(line)
            for line in Path("data/benchmark/dataset-v2.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        runbook = Path("docs/smoke-gpu-runbook.md").read_text(encoding="utf-8")

        self.assertEqual(len(active), 298)
        self.assertEqual(len({row["case_id"] for row in active}), 298)
        self.assertNotIn("jeu final de 300", runbook)
        self.assertIn("298 cas actifs", runbook)
        self.assertIn("piste finale distincte", runbook)
        self.assertIn("éligible qualité", runbook)

    def test_runbook_requires_provider_side_termination_deadline(self):
        runbook = Path("docs/smoke-gpu-runbook.md").read_text(encoding="utf-8")

        self.assertIn('runpodctl pod create --help | grep -q -- "--terminate-after"', runbook)
        self.assertIn('--terminate-after "$PROVIDER_TERMINATE_AFTER"', runbook)
        self.assertIn('PROVIDER_DEADLINE="$(python -c', runbook)
        self.assertIn("--provider-deadline '$PROVIDER_DEADLINE'", runbook)
        self.assertIn("indépendante du watchdog", runbook)

    def test_campaign_receipt_is_the_only_consumable_report_source(self):
        campaign = Path("scripts/run_bge_gpu_campaign.py").read_text(encoding="utf-8")
        runner = Path("scripts/run_bge_gpu_smoke.py").read_text(encoding="utf-8")
        runbook = Path("docs/smoke-gpu-runbook.md").read_text(encoding="utf-8")
        protocol = Path("docs/ablation-protocol.md").read_text(encoding="utf-8")

        self.assertIn("if execution_receipt is not None:", runner)
        self.assertIn(
            'execution_metadata["artifact_source_of_truth"] = "execution_receipt.report"',
            runner,
        )
        self.assertIn("staging non consommable", campaign)
        self.assertIn("l'unique source de", runbook)
        self.assertIn("load_consumable_receipt_v2", runbook)
        self.assertIn('receipt["report"]', runbook)
        self.assertIn("reçu autonome est l'unique artefact consommable", protocol)
        self.assertNotIn("recalculer le SHA-256 du rapport", runbook)
        self.assertNotIn("Copier le rapport et", runbook)

    def test_campaign_attests_and_protects_every_execution_input_before_receipt_run(self):
        manifest_path = campaign.ROOT / "manifests/gpu/bge-m3-human-154.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_attestation = {
            "path": "manifests/gpu/bge-m3-human-154.json",
            "sha256": "a" * 64,
        }
        attested_paths = []

        def attest(_root, path):
            attested_paths.append(Path(path).resolve())
            return {"path": str(path), "sha256": "b" * 64}

        argv = [
            "run_bge_gpu_campaign.py",
            "--code-revision",
            "1" * 40,
        ]
        with (
            patch.object(campaign, "require_code_revision", return_value="1" * 40),
            patch.object(
                campaign,
                "read_repository_json_snapshot",
                return_value=(manifest, manifest_attestation),
                create=True,
            ) as read_manifest,
            patch.object(campaign, "repository_file_attestation", side_effect=attest),
            patch.object(campaign, "run_with_receipt", return_value=0) as run_receipt,
            patch.object(sys, "argv", argv),
        ):
            self.assertEqual(campaign.main(), 0)

        expected_paths = {
            (campaign.ROOT / "docs/ablation-protocol.md").resolve(),
            (campaign.ROOT / manifest["corpus"]["questions"]).resolve(),
        }
        expected_paths.update(
            (campaign.ROOT / item).resolve()
            for item in manifest["corpus"]["documents"]
        )
        expected_paths.update(
            (campaign.ROOT / manifest["models"][key]).resolve()
            for key in ("embedding_lock", "reranker_lock")
        )
        read_manifest.assert_called_once_with(campaign.ROOT, manifest_path)
        self.assertEqual(set(attested_paths), expected_paths)
        protected_paths = {
            Path(path).resolve()
            for path in run_receipt.call_args.kwargs["protected_paths"]
        }
        self.assertEqual(protected_paths, expected_paths | {manifest_path.resolve()})

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

    def test_human_154_job_uses_immutable_reviewed_dataset_snapshot(self):
        path = Path("manifests/gpu/bge-m3-human-154.json")
        plan = load_gpu_job(path)
        manifest = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(plan.job_id, "bge-m3-human-154-a40-v1")
        self.assertEqual(plan.gpu_model, "NVIDIA A40")
        self.assertEqual(plan.minimum_vram_gib, 40)
        self.assertEqual(manifest["campaign"], {
            "expected_cases": 154,
            "expected_abstentions": 32,
            "expected_calibration": 81,
            "expected_holdout": 73,
        })
        self.assertEqual(
            manifest["corpus"]["questions"],
            "data/benchmark/dataset-v2-human-154.jsonl",
        )
        dataset_path = Path(manifest["corpus"]["questions"])
        payload = dataset_path.read_bytes()
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
        self.assertEqual(len(rows), 154)
        self.assertEqual(len({row["case_id"] for row in rows}), 154)
        self.assertEqual(sum(bool(row["should_abstain"]) for row in rows), 32)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "4613e8b3b84fb7b24ad66cf01329f40d95934bec189fe7f6cddf1eb751c767d4",
        )
        corpus_path = Path(manifest["corpus"]["documents"][0])
        validated, questions = human_cases_to_questions(
            rows,
            load_documents(corpus_path),
            corpus_manifest(corpus_path),
        )
        assignments = deterministic_group_split(
            validated,
            salt="bge-m3-abstention-v1",
        )
        self.assertEqual(len(questions), 154)
        self.assertEqual(
            {partition: list(assignments.values()).count(partition) for partition in {"calibration", "holdout"}},
            {"calibration": 81, "holdout": 73},
        )
        self.assertEqual(manifest["corpus"]["question_format"], "evaluation_v2")
        self.assertEqual(
            manifest["corpus"]["documents"],
            ["data/generated/hermes_public_documents-human-154.jsonl"],
        )
        self.assertEqual(
            hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            "af0631abbffaab14b180abc4531497665a6104d6685328d6abbe53a565c53866",
        )

    def test_gpu_runner_uses_snapshot_attestations_for_reported_inputs(self):
        runner = Path("scripts/run_bge_gpu_smoke.py").read_text(encoding="utf-8")

        self.assertIn("read_repository_json_snapshot(", runner)
        self.assertIn("dataset_payload, dataset_attestation = read_repository_snapshot(", runner)
        self.assertIn("protocol_payload, protocol_attestation = read_repository_snapshot(", runner)
        self.assertIn('"manifest_sha256": manifest_attestation["sha256"]', runner)
        self.assertIn('"dataset_sha256": dataset_attestation["sha256"]', runner)
        self.assertIn('"sha256": protocol_attestation["sha256"]', runner)
        self.assertNotIn("manifest_sha = sha256(MANIFEST)", runner)

    def test_gpu_runner_uses_secure_model_lock_snapshots_for_execution_and_report(self):
        runner = Path("scripts/run_bge_gpu_smoke.py").read_text(encoding="utf-8")

        self.assertIn("model_locks = read_model_lock_snapshots(ROOT, manifest)", runner)
        self.assertIn('emb_lock = model_locks["embedding"]["data"]', runner)
        self.assertIn('rerank_lock = model_locks["reranker"]["data"]', runner)
        self.assertIn(
            '"embedding_lock": model_locks["embedding"]["attestation"]', runner
        )
        self.assertIn(
            '"reranker_lock": model_locks["reranker"]["attestation"]', runner
        )
        self.assertNotIn("def load_json(", runner)

    def test_gpu_runner_builds_and_attests_corpus_from_one_secure_snapshot(self):
        runner = Path("scripts/run_bge_gpu_smoke.py").read_text(encoding="utf-8")

        self.assertEqual(
            runner.count("corpus_payload, corpus_attestation = read_repository_snapshot("),
            1,
        )
        self.assertIn("load_documents_payload(corpus_payload)", runner)
        self.assertIn("load_evaluation_documents_payload(corpus_payload)", runner)
        self.assertIn("corpus_manifest_payload(corpus_payload)", runner)
        self.assertIn('"corpus_path": corpus_attestation["path"]', runner)
        self.assertIn('"corpus_sha256": corpus_attestation["sha256"]', runner)
        self.assertNotIn("load_documents(ROOT / item)", runner)
        self.assertNotIn("load_evaluation_documents(corpus_path)", runner)
        self.assertNotIn("corpus_manifest(corpus_path)", runner)

    def test_gpu_runner_publishes_report_atomically(self):
        runner = Path("scripts/run_bge_gpu_smoke.py").read_text(encoding="utf-8")

        self.assertIn("publish_gpu_report_atomic(OUTPUT, ROOT / \"data/results\", report)", runner)
        self.assertNotIn("OUTPUT.write_text(", runner)

    def test_gpu_runner_fixes_and_records_determinism_settings(self):
        runner = Path("scripts/run_bge_gpu_smoke.py").read_text(encoding="utf-8")

        self.assertIn("random.seed(RANDOM_SEED)", runner)
        self.assertIn("np.random.seed(RANDOM_SEED)", runner)
        self.assertIn("torch.manual_seed(RANDOM_SEED)", runner)
        self.assertIn("torch.cuda.manual_seed_all(RANDOM_SEED)", runner)
        self.assertIn("torch.use_deterministic_algorithms(True)", runner)
        self.assertIn('"reproducibility": determinism', runner)
        self.assertIn('"known_limitations":', runner)

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
