"""Advisory, same-host document write exclusion for cooperating Qdrant writers.

The directory and lock files must never be unlinked while writers may run.
All participating processes must use the same local filesystem path and UID.
Direct Qdrant writes or workers on other hosts do not participate.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import time
from typing import Iterator


def default_lock_directory() -> Path:
    return Path.home() / ".local" / "state" / "rag-hermes" / "qdrant-locks"


def _lock_filename(collection: str, tenant_id: str, document_id: str) -> str:
    digest = hashlib.sha256()
    for value in (collection, tenant_id, document_id):
        if type(value) is not str or not value:
            raise ValueError("document lock identity must be a nonempty string")
        raw = value.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest() + ".lock"


@contextmanager
def document_write_lock(
    directory: str | Path,
    collection: str,
    tenant_id: str,
    document_id: str,
    *,
    timeout: float = 30.0,
) -> Iterator[None]:
    """Hold an OS flock across the entire scan/encode/upsert/delete sequence."""
    if type(timeout) not in (int, float) or not 0 <= timeout <= 3600:
        raise ValueError("document lock timeout must be between 0 and 3600 seconds")
    if not isinstance(directory, (str, Path)) or not str(directory):
        raise ValueError("lock directory must be an absolute path")
    root = Path(directory)
    if not root.is_absolute():
        raise ValueError("lock directory must be an absolute path")
    filename = _lock_filename(collection, tenant_id, document_id)
    os.makedirs(root, mode=0o700, exist_ok=True)
    info = os.lstat(root)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise OSError("lock directory must be owned by this user and private")
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(root / filename, flags, 0o600)
    try:
        locked = os.fstat(fd)
        if (
            not stat.S_ISREG(locked.st_mode)
            or locked.st_uid != os.getuid()
            or locked.st_nlink != 1
            or stat.S_IMODE(locked.st_mode) & 0o077
        ):
            raise OSError("document lock file is not private and regular")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("document write lock contention") from exc
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
