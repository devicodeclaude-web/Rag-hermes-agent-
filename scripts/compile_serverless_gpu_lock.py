from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "requirements-serverless-gpu.in"
OUTPUT = ROOT / "requirements-serverless-gpu.lock.txt"
UV_VERSION = "0.13.4"
PYPI_INDEX = "https://pypi.org/simple"
COMPILE_COMMAND = "python -m scripts.compile_serverless_gpu_lock"
EXPECTED_COMPILED_PACKAGE_COUNT = 150
EXPECTED_COMPILED_GRAPH_SHA256 = "1cf334105992eee5bf328bdaa36292c5dbddb980ed8a3b8a865a95f37ff3ff6b"
EXPECTED_COMPILED_CONTENT_SHA256 = "6bf645db7670c52d0618eb058df3d5c54181ade4f18a060873deca395ecaebda"
EXPECTED_FINAL_CONTENT_SHA256 = "149fe07cd6ce77ca5470acc2337bac50b5e14392867f626a9f26a87f011186c4"
TORCH_SHA256 = "4354fc05bb79b208d6995a04ca1ceef6a9547b1c4334435574353d381c55087c"
EXPECTED_TORCH_REQUIREMENT = (
    "torch @ https://download-r2.pytorch.org/whl/cu128/"
    "torch-2.8.0%2Bcu128-cp312-cp312-manylinux_2_28_x86_64.whl"
    f"#sha256={TORCH_SHA256}"
)
EXPECTED_GPU_INPUT_REQUIREMENTS = [
    "FlagEmbedding==1.3.5",
    "huggingface_hub==0.34.4",
    "transformers==4.57.6",
]
EXPECTED_SERVERLESS_INPUT_REQUIREMENTS = ["runpod==1.12.0"]
EXPECTED_TOP_LEVEL_REQUIREMENTS = [
    "-r requirements-gpu.in",
    "-r requirements-serverless.in",
    EXPECTED_TORCH_REQUIREMENT,
]
HASH_LINE_RE = re.compile(r"    --hash=sha256:[0-9a-f]{64}(?: \\)?")
HASH_LINE_CONTINUED_RE = re.compile(r"    --hash=sha256:[0-9a-f]{64} \\")
HASH_LINE_TERMINAL_RE = re.compile(r"    --hash=sha256:[0-9a-f]{64}")
VERSION_PATTERN = (
    r"(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?"
    r"(?:\.post[0-9]+)?(?:\.dev[0-9]+)?"
    r"(?:\+[a-z0-9]+(?:[._-][a-z0-9]+)*)?"
)
PACKAGE_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(" + VERSION_PATTERN + r") "
    + re.escape("\\")
    + r"$"
)
REQUIRED_COMPILED_VERSIONS = {
    "flagembedding": "1.3.5",
    "huggingface-hub": "0.34.4",
    "nvidia-cublas-cu12": "12.8.4.1",
    "nvidia-cuda-runtime-cu12": "12.8.90",
    "runpod": "1.12.0",
    "transformers": "4.57.6",
    "triton": "3.4.0",
}


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements(path: Path) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"cannot read approved requirements input: {path}") from error
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _torch_requirement(input_path: Path = INPUT) -> str:
    top_level = _requirements(input_path)
    if top_level != EXPECTED_TOP_LEVEL_REQUIREMENTS:
        raise RuntimeError(
            "expected exactly the two approved requirement includes and the approved "
            "CPython 3.12 manylinux_2_28 PyTorch wheel"
        )
    included = (
        (
            input_path.parent / "requirements-gpu.in",
            EXPECTED_GPU_INPUT_REQUIREMENTS,
        ),
        (
            input_path.parent / "requirements-serverless.in",
            EXPECTED_SERVERLESS_INPUT_REQUIREMENTS,
        ),
    )
    for path, expected in included:
        if _requirements(path) != expected:
            raise RuntimeError(f"unapproved requirements input content: {path.name}")
    return EXPECTED_TORCH_REQUIREMENT


def _write_input_snapshot(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "requirements-gpu.in").write_text(
        "\n".join(EXPECTED_GPU_INPUT_REQUIREMENTS) + "\n", encoding="utf-8"
    )
    (directory / "requirements-serverless.in").write_text(
        "\n".join(EXPECTED_SERVERLESS_INPUT_REQUIREMENTS) + "\n",
        encoding="utf-8",
    )
    snapshot = directory / "requirements-serverless-gpu.in"
    snapshot.write_text(
        "\n".join(EXPECTED_TOP_LEVEL_REQUIREMENTS) + "\n", encoding="utf-8"
    )
    return snapshot


def _clean_uv_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    blocked = {
        "PIP_CONFIG_FILE",
        "PIP_EXTRA_INDEX_URL",
        "PIP_FIND_LINKS",
        "PIP_INDEX_URL",
        "PIP_NO_INDEX",
        "PIP_TRUSTED_HOST",
    }
    return {
        key: value
        for key, value in source.items()
        if not key.startswith("UV_") and key not in blocked
    }


def _uv_binary(explicit: str | None) -> str:
    candidate = explicit or os.environ.get("UV_BIN") or shutil.which("uv")
    if not candidate:
        raise RuntimeError("uv not found; set UV_BIN to the uv 0.13.4 executable")
    version = subprocess.run(
        [candidate, "--version"],
        check=True,
        capture_output=True,
        text=True,
        env=_clean_uv_environment(),
    ).stdout.strip()
    if not re.fullmatch(rf"uv {re.escape(UV_VERSION)}(?: \([^\n]+\))?", version):
        raise RuntimeError(f"expected uv {UV_VERSION}, got {version!r}")
    return candidate


def _package_blocks(content: str) -> list[tuple[str, str, str]]:
    lines = content.splitlines()
    index = 3
    while index < len(lines) and not lines[index]:
        index += 1

    blocks: list[tuple[str, str, str]] = []
    trailer = ["# The following packages were excluded from the output:", "# torch"]
    while index < len(lines):
        if lines[index:] == trailer:
            break
        match = PACKAGE_RE.fullmatch(lines[index])
        if match is None:
            raise RuntimeError(
                f"compiled lock expected a pinned package at line {index + 1}: "
                f"{lines[index]!r}"
            )
        start = index
        name = _canonical_name(match.group(1))
        version = match.group(2)
        index += 1

        hash_count = 0
        while index < len(lines):
            line = lines[index]
            if HASH_LINE_CONTINUED_RE.fullmatch(line):
                hash_count += 1
                index += 1
                continue
            if HASH_LINE_TERMINAL_RE.fullmatch(line):
                hash_count += 1
                index += 1
                break
            raise RuntimeError(
                f"compiled lock has an invalid hash sequence for package {name}"
            )
        if hash_count == 0:
            raise RuntimeError(f"compiled lock package is not SHA-256 pinned: {name}")

        while index < len(lines) and lines[index].startswith("    #"):
            index += 1
        blocks.append((name, version, "\n".join(lines[start:index])))

        while index < len(lines) and not lines[index]:
            index += 1
        if index < len(lines) and lines[index].startswith("#"):
            if lines[index:] != trailer:
                raise RuntimeError("compiled lock contains an unapproved trailer")
            break

    return blocks


def _package_graph_sha256(blocks: list[tuple[str, str, str]]) -> str:
    graph = "".join(f"{name}=={version}\n" for name, version, _ in sorted(blocks))
    return hashlib.sha256(graph.encode("utf-8")).hexdigest()


def validate_registry_lock(
    content: str,
    *,
    compile_command: str,
    expected_package_count: int,
    required_versions: Mapping[str, str],
    expected_graph_sha256: str,
) -> None:
    lines = content.splitlines()
    if (
        len(lines) < 3
        or lines[0] != "# This file was autogenerated by uv via the following command:"
        or lines[1] != f"#    {compile_command}"
    ):
        raise RuntimeError("compiled lock is missing the exact generator provenance")
    index_lines = [line for line in lines if line.startswith("--index-url ")]
    if index_lines != [f"--index-url {PYPI_INDEX}"]:
        raise RuntimeError("compiled lock must record PyPI as its only package index")
    if any(
        line.startswith(("--extra-index-url ", "--find-links ", "--no-index"))
        for line in lines
    ):
        raise RuntimeError("compiled lock contains an unapproved package source")
    for line in lines:
        if (
            not line
            or line.startswith("#")
            or line == f"--index-url {PYPI_INDEX}"
            or PACKAGE_RE.fullmatch(line)
            or HASH_LINE_RE.fullmatch(line)
            or line.startswith("    #")
        ):
            continue
        raise RuntimeError(f"compiled lock contains an unrecognized line: {line!r}")
    if any(" @ " in line for line in lines if not line.startswith("#")):
        raise RuntimeError("uv output contains an unexpected direct URL requirement")

    first_package = next(
        (index for index, line in enumerate(lines) if PACKAGE_RE.fullmatch(line)), None
    )
    if first_package is None or any(
        HASH_LINE_RE.fullmatch(line) for line in lines[:first_package]
    ):
        raise RuntimeError("compiled lock contains an orphan SHA-256 hash")

    blocks = _package_blocks(content)
    names = [name for name, _, _ in blocks]
    duplicates = sorted(name for name, count in Counter(names).items() if count != 1)
    if duplicates:
        raise RuntimeError(f"compiled lock contains duplicate packages: {duplicates}")
    if len(blocks) != expected_package_count:
        raise RuntimeError(
            "compiled lock package count changed: "
            f"expected {expected_package_count}, got {len(blocks)}"
        )
    graph_sha256 = _package_graph_sha256(blocks)
    if graph_sha256 != expected_graph_sha256:
        raise RuntimeError(
            "compiled lock package graph changed: "
            f"expected {expected_graph_sha256}, got {graph_sha256}"
        )
    for name, _, block in blocks:
        if not any(HASH_LINE_RE.fullmatch(line) for line in block.splitlines()):
            raise RuntimeError(f"compiled lock package is not SHA-256 pinned: {name}")

    versions = {name: version for name, version, _ in blocks}
    for name, expected_version in required_versions.items():
        if versions.get(name) != expected_version:
            raise RuntimeError(
                f"compiled lock has unexpected {name} version: "
                f"expected {expected_version}, got {versions.get(name)!r}"
            )


def _validate_compiled_lock(content: str) -> None:
    validate_registry_lock(
        content,
        compile_command=COMPILE_COMMAND,
        expected_package_count=EXPECTED_COMPILED_PACKAGE_COUNT,
        required_versions=REQUIRED_COMPILED_VERSIONS,
        expected_graph_sha256=EXPECTED_COMPILED_GRAPH_SHA256,
    )
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if content_sha256 != EXPECTED_COMPILED_CONTENT_SHA256:
        raise RuntimeError(
            "compiled lock content changed: "
            f"expected {EXPECTED_COMPILED_CONTENT_SHA256}, got {content_sha256}"
        )


def _validate_final_lock(content: str, torch_requirement: str) -> None:
    torch_lines = [line for line in content.splitlines() if line.startswith("torch @ ")]
    if torch_lines != [torch_requirement]:
        raise RuntimeError("final lock must contain exactly one approved PyTorch requirement")
    suffix = torch_requirement + "\n"
    if not content.endswith(suffix):
        raise RuntimeError("approved PyTorch requirement must be the final lock line")
    without_torch = content[: -len(suffix)]
    expected = without_torch.rstrip() + "\n" + suffix
    if content != expected:
        raise RuntimeError("final lock is not in canonical sequential form")
    _validate_compiled_lock(without_torch)
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if content_sha256 != EXPECTED_FINAL_CONTENT_SHA256:
        raise RuntimeError(
            "final lock content changed: "
            f"expected {EXPECTED_FINAL_CONTENT_SHA256}, got {content_sha256}"
        )


def compile_lock(
    uv: str,
    *,
    input_path: Path = INPUT,
    output_path: Path = OUTPUT,
) -> None:
    torch_requirement = _torch_requirement(input_path)
    temporary: Path | None = None
    with tempfile.TemporaryDirectory(
        prefix=".uv-serverless-lock-cache.", dir=output_path.parent
    ) as cache_directory, tempfile.TemporaryDirectory(
        prefix=".serverless-input.", dir=output_path.parent
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
                "--no-emit-package",
                "torch",
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
            compiled = temporary.read_text(encoding="utf-8")
            _validate_compiled_lock(compiled)
            final = compiled.rstrip() + "\n" + torch_requirement + "\n"
            _validate_final_lock(final, torch_requirement)
            temporary.write_text(final, encoding="utf-8")
            os.replace(temporary, output_path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile the Serverless GPU lock with one exact PyTorch wheel hash."
    )
    parser.add_argument("--uv", help="Path to the uv 0.13.4 executable")
    args = parser.parse_args()
    compile_lock(_uv_binary(args.uv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
