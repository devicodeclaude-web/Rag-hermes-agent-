#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from typing import cast, Sequence

_DOCKERFILE = "containers/serverless/Dockerfile"
_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _git(
    root: Path,
    arguments: Sequence[str],
    *,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=text,
        timeout=120,
        env=_git_environment(),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare_context(repository: Path, output_root: Path) -> Path:
    if repository.is_symlink():
        raise ValueError("repository root must not be a symlink")
    root = repository.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository root must be a directory")

    top_level_output = cast(
        str, _git(root, ["rev-parse", "--show-toplevel"]).stdout
    )
    top_level = Path(top_level_output.strip()).resolve()
    if top_level != root:
        raise ValueError("repository root must be the Git top-level directory")
    revision = cast(str, _git(root, ["rev-parse", "HEAD"]).stdout).strip()
    if _FULL_SHA.fullmatch(revision) is None:
        raise ValueError("repository HEAD must be a full lowercase Git SHA")
    status = cast(
        str,
        _git(root, ["status", "--porcelain=v1", "--untracked-files=all"]).stdout,
    )
    if status:
        raise ValueError("repository must be clean before preparing a build context")

    try:
        dockerfile_payload = cast(
            bytes,
            _git(
                root,
                ["show", f"{revision}:{_DOCKERFILE}"],
                text=False,
            ).stdout,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError("committed Serverless Dockerfile is missing") from exc
    if not isinstance(dockerfile_payload, bytes) or not dockerfile_payload:
        raise ValueError("committed Serverless Dockerfile is empty")

    if output_root.is_symlink():
        raise ValueError("build context output root must not be a symlink")
    output = output_root.resolve(strict=False)
    if output == root or output.is_relative_to(root):
        raise ValueError("build context output must stay outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink() or not output.is_dir():
        raise ValueError("build context output root must be a real directory")

    final_directory = output / revision
    if final_directory.exists() or final_directory.is_symlink():
        raise FileExistsError("build context for this revision already exists")

    temporary_directory = Path(
        tempfile.mkdtemp(prefix=f".{revision}.", dir=output)
    )
    published = False
    try:
        dockerfile_path = temporary_directory / "Dockerfile"
        dockerfile_path.write_bytes(dockerfile_payload)

        snapshot_directory = temporary_directory / ".repository-snapshot"
        snapshot_directory.mkdir()
        _git(snapshot_directory, ["init", "-q"])
        _git(
            snapshot_directory,
            [
                "-c",
                "protocol.file.allow=always",
                "fetch",
                "-q",
                "--depth=1",
                "--no-tags",
                root.as_uri(),
                revision,
            ],
        )
        _git(snapshot_directory, ["checkout", "-q", "--detach", "FETCH_HEAD"])
        snapshot_revision = cast(
            str, _git(snapshot_directory, ["rev-parse", "HEAD"]).stdout
        ).strip()
        snapshot_count = cast(
            str,
            _git(snapshot_directory, ["rev-list", "--count", "HEAD"]).stdout,
        ).strip()
        snapshot_status = cast(
            str,
            _git(
                snapshot_directory,
                ["status", "--porcelain=v1", "--untracked-files=all"],
            ).stdout,
        )
        if snapshot_revision != revision or snapshot_count != "1" or snapshot_status:
            raise RuntimeError("Git did not produce a clean one-commit snapshot")

        archive_path = temporary_directory / "repository.tar"
        with tarfile.open(archive_path, "w", format=tarfile.PAX_FORMAT) as archive:
            for source in sorted(
                snapshot_directory.rglob("*"), key=lambda path: path.as_posix()
            ):
                archive.add(
                    source,
                    arcname=source.relative_to(snapshot_directory).as_posix(),
                    recursive=False,
                )
        shutil.rmtree(snapshot_directory)
        if not archive_path.is_file() or archive_path.is_symlink():
            raise RuntimeError("failed to create a regular repository snapshot")

        manifest = {
            "schema_version": "serverless-build-context.v2",
            "code_revision": revision,
            "dockerfile": {
                "path": "Dockerfile",
                "sha256": _sha256(dockerfile_path),
            },
            "repository_snapshot": {
                "path": "repository.tar",
                "sha256": _sha256(archive_path),
            },
        }
        manifest_path = temporary_directory / "context-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        for path in (dockerfile_path, archive_path, manifest_path):
            path.chmod(0o644)
            _fsync_file(path)
        directory_fd = os.open(temporary_directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        os.replace(temporary_directory, final_directory)
        published = True
        output_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(output_fd)
        finally:
            os.close(output_fd)
        return final_directory
    except Exception:
        if published:
            shutil.rmtree(final_directory)
            cleanup_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(cleanup_fd)
            finally:
                os.close(cleanup_fd)
        else:
            shutil.rmtree(temporary_directory, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare an attested, commit-only Serverless Docker build context."
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
    arguments = parser.parse_args()

    context = prepare_context(arguments.repository, arguments.output_root)
    manifest = json.loads(
        (context / "context-manifest.json").read_text(encoding="utf-8")
    )
    print(
        json.dumps(
            {
                "context": str(context),
                "code_revision": manifest["code_revision"],
                "dockerfile": str(context / "Dockerfile"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
