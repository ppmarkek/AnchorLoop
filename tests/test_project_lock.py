from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from anchorloop.project_lock import ProjectLock, ProjectLockError, ProjectLockTimeout


def _attempt_lock(root: str, timeout: float, queue: multiprocessing.Queue) -> None:
    try:
        with ProjectLock(root, timeout=timeout, purpose="child attempt"):
            queue.put(("acquired", ""))
    except Exception as error:  # pragma: no cover - result is asserted in the parent.
        queue.put((type(error).__name__, str(error)))


def _acquire_then_crash(root: str, ready: multiprocessing.Event) -> None:
    with ProjectLock(root, timeout=2, purpose="crash test"):
        ready.set()
        os._exit(23)


class ProjectLockTests(unittest.TestCase):
    def test_same_thread_reentrancy_keeps_lock_until_outer_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outer = ProjectLock(root, purpose="outer")
            inner = ProjectLock(root, purpose="inner")

            with outer:
                self.assertTrue(ProjectLock.held_by_current_thread(root))
                with inner:
                    self.assertTrue(ProjectLock.held_by_current_thread(root))
                self.assertTrue(ProjectLock.held_by_current_thread(root))

            self.assertFalse(ProjectLock.held_by_current_thread(root))
            metadata = json.loads((root / ".anchor" / "project.lock").read_text(encoding="utf-8"))
            self.assertEqual(metadata["pid"], os.getpid())

    def test_other_thread_waits_for_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acquired = threading.Event()

            def worker() -> None:
                with ProjectLock(root, timeout=2):
                    acquired.set()

            with ProjectLock(root):
                thread = threading.Thread(target=worker)
                thread.start()
                time.sleep(0.1)
                self.assertFalse(acquired.is_set())
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertTrue(acquired.is_set())

    def test_other_process_gets_clear_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = multiprocessing.get_context("spawn")
            queue = context.Queue()
            with ProjectLock(root, timeout=2, purpose="parent command"):
                process = context.Process(target=_attempt_lock, args=(str(root), 0.2, queue))
                process.start()
                process.join(10)

            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
            error_type, message = queue.get(timeout=2)
            self.assertEqual(error_type, ProjectLockTimeout.__name__)
            self.assertIn("Timed out after 0.20s", message)
            self.assertIn("project.lock", message)
            self.assertIn("Retry after the other mutating command finishes", message)

    def test_kernel_releases_lock_when_owner_process_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = multiprocessing.get_context("spawn")
            ready = context.Event()
            process = context.Process(target=_acquire_then_crash, args=(str(root), ready))
            process.start()
            self.assertTrue(ready.wait(10))
            process.join(10)
            self.assertEqual(process.exitcode, 23)

            with ProjectLock(root, timeout=2):
                self.assertTrue(ProjectLock.held_by_current_thread(root))

    def test_release_requires_ownership_by_this_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ProjectLockError):
                ProjectLock(directory).release()


if __name__ == "__main__":
    unittest.main()

