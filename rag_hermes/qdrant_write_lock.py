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
import threading
import time
from typing import Iterator


class DocumentWriteLockTimeout(TimeoutError):
    """An import could not acquire its cooperative document lock in time."""


# Track OPEN file descriptions before flock: an idle child forked by any
# thread otherwise inherits and keeps a parent's lease alive after a crash.
_ACTIVE_FDS_LOCK = threading.Lock()
_ACTIVE_FDS: dict[int, int] = {}
_NEXT_TOKEN = 0


def _after_fork_in_child() -> None:
    for fd in _ACTIVE_FDS.values():
        try:
            os.close(fd)  # Never LOCK_UN: that would unlock the parent's OFD.
        except OSError:
            pass
    _ACTIVE_FDS.clear()
    _ACTIVE_FDS_LOCK.release()


os.register_at_fork(
    before=_ACTIVE_FDS_LOCK.acquire,
    after_in_parent=_ACTIVE_FDS_LOCK.release,
    after_in_child=_after_fork_in_child,
)


def _open_tracked_lock_file(root_fd: int, filename: str) -> tuple[int, int]:
    global _NEXT_TOKEN
    with _ACTIVE_FDS_LOCK:
        fd = os.open(
            filename, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600, dir_fd=root_fd,
        )
        token = _NEXT_TOKEN
        _NEXT_TOKEN += 1
        _ACTIVE_FDS[token] = fd
        return fd, token


def _close_tracked_lock_file(token: int) -> None:
    with _ACTIVE_FDS_LOCK:
        fd = _ACTIVE_FDS.pop(token, None)
        if fd is not None:
            os.close(fd)


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


def _open_private_directory(root: Path) -> int:
    """Open each component from / without following links or trusting writable parents."""
    fd = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        parts = root.parts[1:]
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise OSError("lock directory must be a private subdirectory")
        for index, part in enumerate(parts):
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            try:
                child = os.open(
                    part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=fd,
                )
            except OSError as exc:
                raise OSError(exc.errno, "lock directory contains an unsafe component", part) from exc
            try:
                info = os.fstat(child)
                mode = stat.S_IMODE(info.st_mode)
                if index == len(parts) - 1:
                    trusted = info.st_uid == os.getuid() and not mode & 0o077
                else:
                    trusted = (
                        info.st_uid in (0, os.getuid())
                        and (not mode & 0o022 or (mode & stat.S_ISVTX and info.st_uid in (0, os.getuid())))
                    )
                if not trusted:
                    raise OSError("lock directory has an untrusted ancestor or permissions")
            except BaseException:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


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
    root_fd = _open_private_directory(root)
    try:
        fd, token = _open_tracked_lock_file(root_fd, filename)
    finally:
        os.close(root_fd)
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
                    raise DocumentWriteLockTimeout("document write lock contention") from exc
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            # The child may unwind an inherited context after at-fork cleanup.
            # Its token was removed; never unlock a reused numeric descriptor.
            with _ACTIVE_FDS_LOCK:
                if _ACTIVE_FDS.get(token) == fd:
                    fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        _close_tracked_lock_file(token)
