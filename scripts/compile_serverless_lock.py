from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from scripts.compile_serverless_gpu_lock import (
    PYPI_INDEX,
    _clean_uv_environment,
    _uv_binary,
    validate_registry_lock,
)


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "requirements-serverless.in"
OUTPUT = ROOT / "requirements-serverless.lock.txt"
COMPILE_COMMAND = "python -m scripts.compile_serverless_lock"
EXPECTED_PACKAGE_COUNT = 101
EXPECTED_GRAPH_SHA256 = "faa30d5b8e3300ad9fad7776705578deda1b7ed93f4e22c20dfc38408f3176d3"
EXPECTED_CONTENT_SHA256 = "cb09ee07dabfe3ba3902ca1966b77d28d2f3db9e2693a8aeceb41c95dabde58e"
EXPECTED_REQUIREMENT = "runpod==1.12.0"
REQUIRED_VERSIONS = {"runpod": "1.12.0"}


def _validate_input(input_path: Path = INPUT) -> None:
    requirements = [
        line.strip()
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if requirements != [EXPECTED_REQUIREMENT]:
        raise RuntimeError(
            f"expected exactly one Serverless SDK requirement: {EXPECTED_REQUIREMENT}"
        )


def _write_input_snapshot(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = directory / "requirements-serverless.in"
    snapshot.write_text(EXPECTED_REQUIREMENT + "\n", encoding="utf-8")
    return snapshot


def compile_lock(
    uv: str,
    *,
    input_path: Path = INPUT,
    output_path: Path = OUTPUT,
) -> None:
    _validate_input(input_path)
    temporary: Path | None = None
    with tempfile.TemporaryDirectory(
        prefix=".uv-serverless-sdk-lock-cache.", dir=output_path.parent
    ) as cache_directory, tempfile.TemporaryDirectory(
        prefix=".serverless-sdk-input.", dir=output_path.parent
    ) as input_directory:
        resolver_input = _write_input_snapshot(Path(input_directory))
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{output_path.name}.",
                suffix=".lock.tmp",
                dir=output_path.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            command = [
                uv,
                "pip",
                "compile",
                str(resolver_input),
                "--generate-hashes",
                "--python-platform",
                "x86_64-manylinux_2_28",
                "--python-version",
                "3.12",
                "--default-index",
                PYPI_INDEX,
                "--emit-index-url",
                "--no-annotate",
                "--link-mode",
                "copy",
                "--cache-dir",
                cache_directory,
                "--no-config",
                "--custom-compile-command",
                COMPILE_COMMAND,
                "-o",
                str(temporary),
            ]
            subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                env=_clean_uv_environment(),
            )
            content = temporary.read_text(encoding="utf-8")
            validate_registry_lock(
                content,
                compile_command=COMPILE_COMMAND,
                expected_package_count=EXPECTED_PACKAGE_COUNT,
                required_versions=REQUIRED_VERSIONS,
                expected_graph_sha256=EXPECTED_GRAPH_SHA256,
            )
            content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if content_sha256 != EXPECTED_CONTENT_SHA256:
                raise RuntimeError(
                    "compiled SDK lock content changed: "
                    f"expected {EXPECTED_CONTENT_SHA256}, got {content_sha256}"
                )
            os.replace(temporary, output_path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile the isolated hash-pinned RunPod Serverless SDK lock."
    )
    parser.add_argument("--uv", help="Path to the uv 0.13.4 executable")
    args = parser.parse_args()
    compile_lock(_uv_binary(args.uv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
