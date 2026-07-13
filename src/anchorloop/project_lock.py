from __future__ import annotations

import errno
import json
import math
import os
import socket
import stat
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .safe_fs import AnchorError, SafeProjectFS


DEFAULT_LOCK_TIMEOUT = 10.0
DEFAULT_POLL_INTERVAL = 0.05


class ProjectLockError(AnchorError):
    """Raised when the project mutation lock cannot be used safely."""


class ProjectLockTimeout(ProjectLockError):
    """Raised when another thread or process holds the project lock too long."""


@dataclass
class _HeldLock:
    pid: int
    thread_id: int
    depth: int
    descriptor: int | None = None
    purpose: str | None = None


_registry_condition = threading.Condition()
_registry: dict[str, _HeldLock] = {}


class ProjectLock:
    """Cross-platform, re-entrant lock for one project's mutating commands.

    The operating-system lock protects against other processes. A small
    process-local registry also serializes threads and permits nested locking
    by the same thread. The lock is released by the kernel if the process dies.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        timeout: float = DEFAULT_LOCK_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        purpose: str | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("Project lock timeout must be a finite non-negative number.")
        if not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("Project lock poll interval must be a finite positive number.")

        self.fs = SafeProjectFS(Path(root))
        self.root = self.fs.root
        self.anchor_dir = self.fs.path(".anchor")
        self.path = self.fs.path(".anchor", "project.lock")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.purpose = purpose.strip() if purpose and purpose.strip() else None
        if self.purpose and len(self.purpose) > 256:
            raise ValueError("Project lock purpose must not exceed 256 characters.")
        self._local_depth = 0
        self._owner_thread: int | None = None

    def __enter__(self) -> ProjectLock:
        return self.acquire()

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.release()

    def acquire(self) -> ProjectLock:
        """Acquire the project lock or raise ``ProjectLockTimeout``."""

        pid = os.getpid()
        thread_id = threading.get_ident()
        if self._local_depth and self._owner_thread != thread_id:
            raise ProjectLockError("A ProjectLock instance cannot be shared across owning threads.")

        key = self._key
        deadline = time.monotonic() + self.timeout
        claimed = False
        with _registry_condition:
            while True:
                held = _registry.get(key)
                if held is None:
                    _registry[key] = _HeldLock(
                        pid=pid,
                        thread_id=thread_id,
                        depth=1,
                        purpose=self.purpose,
                    )
                    claimed = True
                    break
                if held.pid == pid and held.thread_id == thread_id and held.descriptor is not None:
                    held.depth += 1
                    self._local_depth += 1
                    self._owner_thread = thread_id
                    return self

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    owner = self._format_registry_owner(held)
                    raise ProjectLockTimeout(self._timeout_message(owner))
                _registry_condition.wait(min(self.poll_interval, remaining))

        descriptor: int | None = None
        acquired_os_lock = False
        try:
            self.fs.ensure_directory(self.anchor_dir)
            descriptor = self._open_lock_file()
            owner: dict[str, Any] | None = None
            while True:
                try:
                    self._try_os_lock(descriptor)
                    acquired_os_lock = True
                    break
                except OSError as error:
                    if not self._is_lock_contention(error):
                        raise ProjectLockError(
                            f"Cannot acquire AnchorLoop project lock at {self.path}: {error}"
                        ) from error
                    owner = self._read_metadata(descriptor)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProjectLockTimeout(self._timeout_message(self._format_file_owner(owner))) from error
                    time.sleep(min(self.poll_interval, remaining))

            self._write_metadata(descriptor)
            with _registry_condition:
                held = _registry.get(key)
                if held is None or held.pid != pid or held.thread_id != thread_id:
                    raise ProjectLockError("The process-local project lock claim was lost.")
                held.descriptor = descriptor
                self._local_depth += 1
                self._owner_thread = thread_id
            descriptor = None
            return self
        except BaseException:
            if descriptor is not None:
                if acquired_os_lock:
                    self._unlock_os_lock(descriptor)
                os.close(descriptor)
            if claimed:
                with _registry_condition:
                    held = _registry.get(key)
                    if held is not None and held.pid == pid and held.thread_id == thread_id:
                        del _registry[key]
                        _registry_condition.notify_all()
            raise

    def release(self) -> None:
        """Release one nesting level held by the current thread."""

        pid = os.getpid()
        thread_id = threading.get_ident()
        if self._local_depth <= 0:
            raise ProjectLockError("Cannot release a project lock that this instance does not hold.")
        if self._owner_thread != thread_id:
            raise ProjectLockError("Only the thread that acquired the project lock may release it.")

        key = self._key
        with _registry_condition:
            held = _registry.get(key)
            if held is None or held.pid != pid or held.thread_id != thread_id:
                raise ProjectLockError("The process-local project lock ownership record is missing.")

            held.depth -= 1
            self._local_depth -= 1
            if self._local_depth == 0:
                self._owner_thread = None
            if held.depth > 0:
                return

            descriptor = held.descriptor
            try:
                if descriptor is not None:
                    self._unlock_os_lock(descriptor)
                    os.close(descriptor)
            finally:
                del _registry[key]
                _registry_condition.notify_all()

    @classmethod
    def held_by_current_thread(cls, root: str | Path) -> bool:
        """Return whether this thread currently owns ``root``'s project lock."""

        fs = SafeProjectFS(Path(root))
        key = os.path.normcase(str(fs.path(".anchor", "project.lock")))
        with _registry_condition:
            held = _registry.get(key)
            return bool(
                held
                and held.pid == os.getpid()
                and held.thread_id == threading.get_ident()
                and held.descriptor is not None
                and held.depth > 0
            )

    @classmethod
    def assert_held(cls, root: str | Path) -> None:
        if not cls.held_by_current_thread(root):
            raise ProjectLockError(
                "A mutating AnchorLoop operation requires the project lock. "
                "Wrap it in: with ProjectLock(project_root):"
            )

    @property
    def _key(self) -> str:
        return os.path.normcase(str(self.path))

    def _open_lock_file(self) -> int:
        self.fs.validate(self.path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as error:
            raise ProjectLockError(f"Cannot safely open project lock at {self.path}: {error}") from error

        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ProjectLockError(f"Project lock path must be a regular file: {self.path}")
            validated = self.fs.validate(self.path, require_exists=True)
            current = os.lstat(validated)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ProjectLockError("Project lock file changed while it was being opened.")
            if opened.st_size == 0:
                os.write(descriptor, b" ")
                os.fsync(descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _try_os_lock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return

        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_os_lock(descriptor: int) -> None:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                return

            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            # Closing the descriptor is the final, kernel-backed release path.
            pass

    @staticmethod
    def _is_lock_contention(error: OSError) -> bool:
        return error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
            error, "winerror", None
        ) in {32, 33, 36}

    def _write_metadata(self, descriptor: int) -> None:
        metadata = {
            "schema_version": 1,
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "hostname": socket.gethostname(),
            "acquired_at": datetime.now(UTC).isoformat(),
            "purpose": self.purpose,
        }
        encoded = (json.dumps(metadata, sort_keys=True) + "\n").encode("utf-8")
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            written = 0
            while written < len(encoded):
                count = os.write(descriptor, encoded[written:])
                if count <= 0:
                    raise OSError("Project lock metadata write made no progress.")
                written += count
            os.ftruncate(descriptor, len(encoded))
            os.fsync(descriptor)
        except OSError as error:
            raise ProjectLockError(f"Cannot record project lock ownership at {self.path}: {error}") from error

    @staticmethod
    def _read_metadata(descriptor: int) -> dict[str, Any] | None:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            raw = os.read(descriptor, 4096).decode("utf-8")
            parsed = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _timeout_message(self, owner: str | None) -> str:
        detail = f" The lock appears to be held by {owner}." if owner else ""
        return (
            f"Timed out after {self.timeout:.2f}s waiting for the AnchorLoop project lock at "
            f"{self.path}.{detail} Retry after the other mutating command finishes."
        )

    @staticmethod
    def _format_registry_owner(held: _HeldLock) -> str:
        owner = f"pid {held.pid}, thread {held.thread_id}"
        return f"{owner} ({held.purpose})" if held.purpose else owner

    @staticmethod
    def _format_file_owner(owner: dict[str, Any] | None) -> str | None:
        if not owner:
            return None
        parts = []
        if owner.get("pid") is not None:
            parts.append(f"pid {owner['pid']}")
        if owner.get("hostname"):
            parts.append(f"host {owner['hostname']}")
        if owner.get("purpose"):
            parts.append(str(owner["purpose"]))
        return ", ".join(parts) or None


def _clear_registry_after_fork() -> None:
    global _registry_condition, _registry
    for held in _registry.values():
        if held.descriptor is not None:
            try:
                os.close(held.descriptor)
            except OSError:
                pass
    _registry = {}
    _registry_condition = threading.Condition()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_clear_registry_after_fork)
