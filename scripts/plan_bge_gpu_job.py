#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from rag_hermes.gpu_job import load_gpu_job


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/gpu/bge-m3-smoke-rtx4090.json"),
    )
    args = parser.parse_args()
    plan = load_gpu_job(args.manifest)
    output = asdict(plan)
    output["mode"] = "validation-only-no-download-no-cloud-spend"
    output["required_model_gib"] = round(plan.required_model_bytes / (1024**3), 3)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
