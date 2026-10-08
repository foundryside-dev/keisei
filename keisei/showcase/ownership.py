"""POSIX process ownership for the showcase runner's database and heartbeat."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def acquire_showcase_ownership(db_path: str) -> Iterator[None]:
    """Hold exclusive ownership until exit; the OS releases it after a crash.

    Keep the lock file in place: unlinking it could let another runner lock a
    different inode while the original owner still holds its lock.
    """
    canonical_db = Path(db_path).resolve()
    lock_path = Path(f"{canonical_db}.showcase.lock")
    with lock_path.open("a") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Showcase runner already owns database: {canonical_db}") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
