from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class BenchmarkManifest:
    data: Mapping[str, Any]
    configuration_id: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BenchmarkManifest":
        required_sections = {"model", "weights", "runtime", "hardware", "workload"}
        missing = required_sections.difference(value)
        if missing:
            raise ValueError(f"missing manifest sections: {sorted(missing)}")

        model = value["model"]
        weights = value["weights"]
        runtime = value["runtime"]
        hardware = value["hardware"]
        workload = value["workload"]

        if not _HEX_40.fullmatch(str(model.get("revision", ""))):
            raise ValueError("model.revision must be an exact 40-character commit hash")
        if not _HEX_64.fullmatch(str(weights.get("artifact_sha256", ""))):
            raise ValueError("weights.artifact_sha256 must be a SHA-256 digest")
        if not model.get("license"):
            raise ValueError("model.license is required")

        engine = runtime.get("engine")
        weight_format = weights.get("format")
        if engine == "llama.cpp" and weight_format != "gguf":
            raise ValueError("llama.cpp delivery manifests require GGUF weights")
        if engine == "vllm" and weight_format not in {"awq", "fp8", "bf16"}:
            raise ValueError("vLLM delivery manifests require AWQ, FP8, or BF16 weights")
        if engine not in {"llama.cpp", "vllm"}:
            raise ValueError("runtime.engine must be llama.cpp or vllm")

        if int(hardware.get("gpu_count", 0)) < 1:
            raise ValueError("hardware.gpu_count must be positive")
        if int(hardware.get("vram_gib", 0)) < 1:
            raise ValueError("hardware.vram_gib must be positive")
        if int(workload.get("context_length", 0)) < 1:
            raise ValueError("workload.context_length must be positive")
        if int(workload.get("concurrent_users", 0)) < 1:
            raise ValueError("workload.concurrent_users must be positive")

        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        configuration_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return cls(data=dict(value), configuration_id=configuration_id)
