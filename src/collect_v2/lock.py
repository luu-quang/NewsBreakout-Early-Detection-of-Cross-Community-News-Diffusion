"""Cross-platform run lock so two overlapping polls never write concurrently.

Backed by ``filelock``, which uses ``fcntl`` on POSIX and ``msvcrt``/Windows
file locking under the hood - the OS releases the lock automatically if the
holding process dies, so a stale lock from a killed process cannot wedge
future runs (unlike a naive "lock file exists" check).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from filelock import FileLock, Timeout


class RunAlreadyInProgress(Exception):
    pass


@contextmanager
def run_lock(lock_path: Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Acquire ``lock_path`` for the duration of the ``with`` block.

    Raises ``RunAlreadyInProgress`` immediately (after ``timeout`` seconds of
    waiting) rather than blocking indefinitely, so an overlapping scheduled
    run fails fast and visibly instead of queuing up.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path), timeout=timeout)
    try:
        with lock:
            yield
    except Timeout as exc:
        raise RunAlreadyInProgress(f"could not acquire {lock_path} within {timeout}s") from exc
