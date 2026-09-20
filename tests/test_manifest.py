import unittest

from rag_hermes.manifest import BenchmarkManifest


LLAMA_MANIFEST = {
    "model": {
        "repo_id": "org/model-gguf",
        "revision": "a" * 40,
        "license": "Apache-2.0",
        "parameters_billion": 14.7,
    },
    "weights": {
        "format": "gguf",
        "quantization": "Q4_K_M",
        "artifact_sha256": "b" * 64,
    },
    "runtime": {
        "engine": "llama.cpp",
        "version": "b5000",
        "arguments": ["--ctx-size", "8192"],
    },
    "hardware": {
        "gpu_model": "NVIDIA RTX 4090",
        "gpu_count": 1,
        "vram_gib": 24,
        "ram_gib": 64,
    },
    "workload": {
        "context_length": 8192,
        "max_output_tokens": 512,
        "concurrent_users": 1,
        "batch_size": 1,
    },
}


class ManifestTests(unittest.TestCase):
    def test_valid_manifest_has_stable_configuration_id(self):
        first = BenchmarkManifest.from_dict(LLAMA_MANIFEST)
        second = BenchmarkManifest.from_dict(dict(reversed(LLAMA_MANIFEST.items())))
        self.assertEqual(first.configuration_id, second.configuration_id)
        self.assertEqual(len(first.configuration_id), 16)

    def test_llama_cpp_requires_gguf(self):
        manifest = {**LLAMA_MANIFEST, "weights": {**LLAMA_MANIFEST["weights"], "format": "awq"}}
        with self.assertRaises(ValueError):
            BenchmarkManifest.from_dict(manifest)

    def test_vllm_rejects_gguf_delivery_manifest(self):
        manifest = {
            **LLAMA_MANIFEST,
            "runtime": {**LLAMA_MANIFEST["runtime"], "engine": "vllm"},
        }
        with self.assertRaises(ValueError):
            BenchmarkManifest.from_dict(manifest)

    def test_checkpoint_revision_and_artifact_hash_are_mandatory(self):
        manifest = {
            **LLAMA_MANIFEST,
            "weights": {**LLAMA_MANIFEST["weights"], "artifact_sha256": ""},
        }
        with self.assertRaises(ValueError):
            BenchmarkManifest.from_dict(manifest)


if __name__ == "__main__":
    unittest.main()
