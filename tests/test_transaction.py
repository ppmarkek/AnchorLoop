from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from anchorloop.project import AnchorProject
from anchorloop.project_lock import ProjectLock, ProjectLockError
from anchorloop.safe_fs import AnchorError
from anchorloop.transaction import (
    DEFAULT_COMPLETED_RECEIPT_RETENTION,
    TransactionError,
    TransactionRecoveryConflict,
    TransactionManager,
    TransactionRecoveryRequired,
    _digest,
)


class _FailAfterFirstOperation(TransactionManager):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root)
        self._operation_count = 0

    def _apply_operation(self, operation: dict[str, object]) -> bool:
        changed = super()._apply_operation(operation)
        self._operation_count += 1
        if self._operation_count == 1:
            raise AnchorError("injected failure after first state write")
        return changed


class _CrashAfterFirstOperation(TransactionManager):
    def _apply_operation(self, operation: dict[str, object]) -> bool:
        super()._apply_operation(operation)
        os._exit(37)


def _crash_between_state_and_event(root: str) -> None:
    with ProjectLock(root, timeout=2, purpose="transaction crash test"):
        manager = _CrashAfterFirstOperation(root)
        transaction = manager.begin(transaction_id="process-crash", command="start")
        transaction.write_text(".anchor/state-a.txt", "A\n")
        transaction.write_text(".anchor/state-b.txt", "B\n")
        transaction.emit_event({"type": "task.started", "task_id": "crash-task"})
        transaction.commit()


def _review_ready_project(root: Path) -> AnchorProject:
    project = AnchorProject.at(root)
    project.apply_setup("add")
    project.start_task("Serialize workflow commands")
    project.record_brief(
        by="Ada Engineer",
        values={
            "outcome": "Keep the task state valid.",
            "scope": "Only the active workflow task.",
            "constraints": "Preserve command behavior.",
            "invariant": "Every state transition remains recorded.",
            "uncertainty": "Command ordering is not predetermined.",
        },
    )
    project.plan_task(
        "Apply the smallest valid state transition.",
        mode="FAST",
        task_type="general",
        mode_override_reason="This deterministic fixture exercises only local workflow state.",
    )
    project.approve_task("Ada Engineer")
    project.transition("implement")
    project.transition("review")
    return project


def _run_competing_task_mutation(
    root: str,
    action: str,
    barrier: Any,
    queue: Any,
) -> None:
    project = AnchorProject.at(root)
    barrier.wait()
    try:
        if action == "precommit":
            project.precommit()
        elif action == "revise":
            project.revise_task(
                target="implement",
                reason="Return to the implementation state.",
            )
        else:  # pragma: no cover - the parent supplies fixed actions.
            raise AssertionError(f"Unknown competing action: {action}")
    except AnchorError as error:
        queue.put((action, f"error:{error}"))
    else:
        queue.put((action, "ok"))


class TransactionTests(unittest.TestCase):
    def test_completed_receipts_are_pruned_to_bounded_retention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ProjectLock(root):
                manager = TransactionManager(root, completed_receipt_retention=10)
                self.assertEqual(DEFAULT_COMPLETED_RECEIPT_RETENTION, 128)
                for sequence in range(5):
                    transaction = manager.begin(transaction_id=f"receipt-{sequence}")
                    transaction.emit_event({"type": "retention.test", "sequence": sequence})
                    transaction.commit()
                bounded = TransactionManager(root, completed_receipt_retention=3)
                bounded.recover()
                final = bounded.begin(transaction_id="receipt-5")
                final.emit_event({"type": "retention.test", "sequence": 5})
                final.commit()

                reused = bounded.begin(transaction_id="receipt-0")
                reused.write_text(".anchor/conflicting-reuse.txt", "must not be applied")
                reused.emit_event({"type": "retention.test", "sequence": 999})
                with self.assertRaises(TransactionError):
                    reused.commit()

            completed = root / ".anchor" / "transactions" / "completed"
            self.assertEqual(
                {path.stem for path in completed.glob("*.json")},
                {"receipt-3", "receipt-4", "receipt-5"},
            )
            self.assertEqual([event["sequence"] for event in self._events(root)], list(range(6)))
            self.assertFalse((root / ".anchor" / "conflicting-reuse.txt").exists())

    def test_receipt_gc_never_removes_a_receipt_with_pending_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ProjectLock(root):
                manager = TransactionManager(root, completed_receipt_retention=10)
                transactions = []
                for sequence in range(4):
                    transaction = manager.begin(transaction_id=f"protected-{sequence}")
                    transaction.write_text(f".anchor/state-{sequence}.txt", str(sequence))
                    transaction.commit()
                    transactions.append(transaction)

                protected_record = manager._record_for(transactions[0])
                manager._write_json(manager._pending_path("protected-0"), protected_record)
                bounded = TransactionManager(root, completed_receipt_retention=2)
                bounded._prune_completed_receipts()

            completed = root / ".anchor" / "transactions" / "completed"
            self.assertEqual(
                {path.stem for path in completed.glob("*.json")},
                {"protected-0", "protected-3"},
            )

    def test_setup_migrates_gitignores_without_removing_user_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = AnchorProject.at(root)
            project.apply_setup("add")
            project_gitignore = root / ".gitignore"
            anchor_gitignore = root / ".anchor" / ".gitignore"
            project_user_content = "# Project policy\ncustom-cache/\n/cache/\n"
            anchor_user_content = "# Anchor policy\ncustom-artifacts/\ncache/\n"
            project_gitignore.write_text(project_user_content, encoding="utf-8")
            anchor_gitignore.write_text(anchor_user_content, encoding="utf-8")

            project.apply_setup("add")

            project_content = project_gitignore.read_text(encoding="utf-8")
            self.assertTrue(project_content.startswith(project_user_content))
            for required in (
                "/cache/",
                "/.cache/",
                "/.anchor/cache/",
                "/.npm/",
                "/.npm-cache/",
                "graphify-out/",
                "__pycache__/",
                "*.py[cod]",
            ):
                self.assertEqual(project_content.splitlines().count(required), 1)
            self.assertIn("custom-cache/", project_content.splitlines())

            anchor_content = anchor_gitignore.read_text(encoding="utf-8")
            self.assertTrue(anchor_content.startswith(anchor_user_content))
            for required in (
                "cache/",
                "logs/",
                "graphify/query-history.jsonl",
                "project.lock",
                "transactions/",
                "outbox/",
            ):
                self.assertEqual(anchor_content.splitlines().count(required), 1)
            self.assertIn("custom-artifacts/", anchor_content.splitlines())

    def test_concurrent_precommit_and_revise_have_serializable_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = _review_ready_project(root)
            task_id = json.loads(project.active_task_path.read_text(encoding="utf-8"))["id"]
            context = multiprocessing.get_context("spawn")
            barrier = context.Barrier(3)
            queue = context.Queue()
            processes = [
                context.Process(
                    target=_run_competing_task_mutation,
                    args=(str(root), action, barrier, queue),
                )
                for action in ("precommit", "revise")
            ]
            for process in processes:
                process.start()
            barrier.wait()
            for process in processes:
                process.join(20)
                self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode, 0)
            outcomes = dict(queue.get(timeout=2) for _ in processes)

            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["state"], "implementing")
            self.assertEqual(outcomes["revise"], "ok")
            self.assertTrue(
                outcomes["precommit"] == "ok"
                or "while task is 'implementing'" in outcomes["precommit"]
            )
            events = self._events(root)
            event_ids = [event["event_id"] for event in events]
            self.assertEqual(len(event_ids), len(set(event_ids)))
            task_event_types = [event["type"] for event in events if event.get("task_id") == task_id]
            self.assertEqual(task_event_types, [event["type"] for event in task["events"]])
            self.assertEqual(task_event_types[-1], "task.revise.implement")
            with ProjectLock(root):
                health = TransactionManager(root).inspect()
            self.assertEqual(health.pending_transactions, 0)
            self.assertEqual(health.outbox_events, 0)

    def test_commit_is_durable_and_retry_with_same_id_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ProjectLock(root):
                manager = TransactionManager(root)
                transaction = manager.begin(transaction_id="task-start-1", command="start")
                transaction.write_json(".anchor/tasks/active.json", {"id": "task-1", "state": "briefing"})
                transaction.write_text(".anchor/next-action.md", "Record the brief.\n")
                transaction.emit_event({"type": "task.started", "task_id": "task-1"})
                result = transaction.commit()

                retry = manager.begin(transaction_id="task-start-1", command="start")
                retry.write_json(".anchor/tasks/active.json", {"id": "task-1", "state": "briefing"})
                retry.write_text(".anchor/next-action.md", "Record the brief.\n")
                retry.emit_event({"type": "task.started", "task_id": "task-1"})
                retry_result = retry.commit()

            self.assertEqual(result.applied_operations, 2)
            self.assertEqual(result.delivered_events, 1)
            self.assertTrue(retry_result.already_committed)
            events = self._events(root)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_id"], "task-start-1:0000")
            self.assertEqual(events[0]["transaction_id"], "task-start-1")
            self.assertFalse((root / ".anchor" / "transactions" / "pending" / "task-start-1.json").exists())
            self.assertTrue((root / ".anchor" / "transactions" / "completed" / "task-start-1.json").is_file())

    def test_recovery_replays_partial_multi_file_write_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ProjectLock(root):
                failing = _FailAfterFirstOperation(root)
                transaction = failing.begin(transaction_id="partial-write", command="approve-rule")
                transaction.write_text(".anchor/state-a.txt", "A\n")
                transaction.write_text(".anchor/state-b.txt", "B\n")
                transaction.emit_event({"type": "rule.approved", "rule_id": "security-v2"})
                with self.assertRaises(TransactionRecoveryRequired):
                    transaction.commit()

                self.assertEqual((root / ".anchor" / "state-a.txt").read_text(encoding="utf-8"), "A\n")
                self.assertFalse((root / ".anchor" / "state-b.txt").exists())
                blocked = TransactionManager(root).begin(transaction_id="must-wait-for-recovery")
                blocked.write_text(".anchor/unrelated.txt", "unsafe ordering\n")
                with self.assertRaises(TransactionRecoveryRequired):
                    blocked.commit()
                self.assertFalse((root / ".anchor" / "unrelated.txt").exists())
                report = TransactionManager(root).recover()

            self.assertEqual(report.recovered_transactions, 1)
            self.assertEqual((root / ".anchor" / "state-b.txt").read_text(encoding="utf-8"), "B\n")
            self.assertEqual(len(self._events(root)), 1)

    def test_recovery_conflict_preserves_post_crash_edit_to_user_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".gitignore"
            target.write_text("existing-user-rule/\n", encoding="utf-8")
            with ProjectLock(root):
                manager = TransactionManager(root)
                manager._ensure_directories()
                transaction = manager.begin(
                    transaction_id="gitignore-post-crash-edit",
                    command="project.setup",
                )
                transaction.write_text(target, "existing-user-rule/\n.anchor/cache/\n")
                record = manager._record_for(transaction)
                operation = record["operations"][0]
                self.assertEqual(operation["before"]["state"], "existing")
                self.assertIn("content_sha256", operation["before"])
                self.assertIn("mode", operation["before"])
                self.assertIn("mode", operation)
                manager._write_json(manager._pending_path(transaction.transaction_id), record)

                user_edit = "existing-user-rule/\nmy-local-policy/\n"
                target.write_text(user_edit, encoding="utf-8")
                with self.assertRaisesRegex(
                    TransactionRecoveryConflict,
                    r"refused to overwrite.*manual",
                ):
                    manager.recover()

            self.assertEqual(target.read_text(encoding="utf-8"), user_edit)
            self.assertTrue(
                (root / ".anchor" / "transactions" / "pending" / "gitignore-post-crash-edit.json").is_file()
            )

    def test_recovery_conflict_preserves_post_crash_edit_to_delete_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".graphifyignore"
            target.write_text("initial-rule\n", encoding="utf-8")
            with ProjectLock(root):
                manager = TransactionManager(root)
                manager._ensure_directories()
                transaction = manager.begin(
                    transaction_id="delete-post-crash-edit",
                    command="project.setup",
                )
                transaction.delete(target)
                record = manager._record_for(transaction)
                operation = record["operations"][0]
                self.assertEqual(operation["before"]["state"], "existing")
                self.assertIn("content_sha256", operation["before"])
                self.assertIn("mode", operation["before"])
                manager._write_json(manager._pending_path(transaction.transaction_id), record)

                user_edit = "initial-rule\nmanual-override\n"
                target.write_text(user_edit, encoding="utf-8")
                with self.assertRaisesRegex(TransactionRecoveryConflict, r"refused to overwrite"):
                    manager.recover()

            self.assertEqual(target.read_text(encoding="utf-8"), user_edit)
            self.assertTrue(
                (root / ".anchor" / "transactions" / "pending" / "delete-post-crash-edit.json").is_file()
            )

    def test_legacy_pending_journal_fails_closed_unless_state_is_already_desired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".gitignore"
            target.write_text("before\n", encoding="utf-8")
            with ProjectLock(root):
                manager = TransactionManager(root)
                manager._ensure_directories()
                transaction = manager.begin(
                    transaction_id="legacy-no-before-state",
                    command="project.setup",
                )
                transaction.write_text(target, "desired\n")
                current = manager._record_for(transaction)
                legacy_operations = []
                for operation in current["operations"]:
                    legacy_operations.append(
                        {
                            key: value
                            for key, value in operation.items()
                            if key not in {"before", "mode"}
                        }
                    )
                specification = {
                    "transaction_id": transaction.transaction_id,
                    "command": transaction.command,
                    "operations": legacy_operations,
                    "events": current["events"],
                }
                legacy = {
                    "schema_version": 1,
                    **specification,
                    "created_at": current["created_at"],
                    "spec_digest": _digest(specification),
                    "journal_digest": _digest(
                        {**specification, "created_at": current["created_at"]}
                    ),
                }
                manager._write_json(manager._pending_path(transaction.transaction_id), legacy)

                with self.assertRaisesRegex(
                    TransactionRecoveryConflict,
                    r"Legacy schema-v1 journal lacks a before-state",
                ):
                    manager.recover()
                self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

                # Match the transaction payload byte-for-byte: Path.write_text
                # newline translation on Windows would otherwise create CRLF.
                target.write_bytes(b"desired\n")
                report = manager.recover()

            self.assertEqual(report.recovered_transactions, 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "desired\n")
            self.assertFalse(
                (root / ".anchor" / "transactions" / "pending" / "legacy-no-before-state.json").exists()
            )

    @unittest.skipIf(os.name == "nt", "POSIX permission bits do not round-trip on Windows")
    def test_recovery_conflict_preserves_post_crash_mode_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".gitignore"
            target.write_text("before\n", encoding="utf-8")
            os.chmod(target, 0o640)
            with ProjectLock(root):
                manager = TransactionManager(root)
                manager._ensure_directories()
                transaction = manager.begin(
                    transaction_id="mode-post-crash-edit",
                    command="project.setup",
                )
                transaction.write_text(target, "after\n")
                record = manager._record_for(transaction)
                manager._write_json(manager._pending_path(transaction.transaction_id), record)

                os.chmod(target, 0o600)
                with self.assertRaisesRegex(TransactionRecoveryConflict, r"permissions"):
                    manager.recover()

            self.assertEqual(target.read_text(encoding="utf-8"), "before\n")
            self.assertEqual(target.stat().st_mode & 0o7777, 0o600)

    def test_process_crash_between_state_write_and_event_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = multiprocessing.get_context("spawn")
            process = context.Process(target=_crash_between_state_and_event, args=(str(root),))
            process.start()
            process.join(10)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 37)

            self.assertEqual((root / ".anchor" / "state-a.txt").read_text(encoding="utf-8"), "A\n")
            self.assertFalse((root / ".anchor" / "state-b.txt").exists())
            with ProjectLock(root, timeout=2):
                report = TransactionManager(root).recover()

            self.assertEqual(report.recovered_transactions, 1)
            self.assertEqual((root / ".anchor" / "state-b.txt").read_text(encoding="utf-8"), "B\n")
            self.assertEqual(len(self._events(root)), 1)

    def test_recovery_does_not_duplicate_event_after_append_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ProjectLock(root):
                manager = TransactionManager(root)
                original_unlink = manager.fs.unlink
                failed = False

                def fail_first_outbox_unlink(path: Path, *, missing_ok: bool = False) -> None:
                    nonlocal failed
                    if not failed and path.parent == manager.outbox_dir:
                        failed = True
                        raise AnchorError("injected crash after event append")
                    original_unlink(path, missing_ok=missing_ok)

                manager.fs.unlink = fail_first_outbox_unlink  # type: ignore[method-assign]
                transaction = manager.begin(transaction_id="event-crash", command="review")
                transaction.write_text(".anchor/state.txt", "ready\n")
                transaction.emit_event({"type": "task.review_ready"})
                with self.assertRaises(TransactionRecoveryRequired):
                    transaction.commit()

                self.assertEqual(len(self._events(root)), 1)
                report = TransactionManager(root).recover()

            self.assertEqual(report.recovered_transactions, 1)
            self.assertEqual(report.delivered_events, 0)
            self.assertEqual(len(self._events(root)), 1)

    def test_recovery_repairs_only_a_torn_final_jsonl_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ProjectLock(root):
                manager = TransactionManager(root)
                first = manager.begin(transaction_id="first-event")
                first.emit_event({"type": "first"})
                first.commit()

                event_log = root / ".anchor" / "events.jsonl"
                with event_log.open("ab") as stream:
                    stream.write(b'{"event_id":"torn')

                second = manager.begin(transaction_id="second-event")
                second.emit_event({"type": "second"})
                second.commit()

            events = self._events(root)
            self.assertEqual([event["type"] for event in events], ["first", "second"])

    def test_torn_event_guidance_uses_the_active_command_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ProjectLock(root):
                manager = TransactionManager(root)
                manager._ensure_directories()
                manager.event_log_path.write_text('{"event_id":"torn', encoding="utf-8")
                with mock.patch.dict(
                    os.environ,
                    {"ANCHORLOOP_COMMAND": "npx --yes anchorloop@0.1.0"},
                ):
                    with self.assertRaisesRegex(
                        TransactionRecoveryRequired,
                        r"npx --yes anchorloop@0\.1\.0 doctor --repair",
                    ):
                        manager._read_event_log(repair_torn_tail=False)

    def test_outbox_preserves_event_order_within_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ProjectLock(root):
                manager = TransactionManager(root)
                transaction = manager.begin(transaction_id="ordered-events")
                for sequence in range(12):
                    transaction.emit_event({"type": "ordered", "sequence": sequence})
                transaction.commit()

            events = self._events(root)
            self.assertEqual([event["sequence"] for event in events], list(range(12)))

    def test_commit_requires_project_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = TransactionManager(directory)
            transaction = manager.begin(transaction_id="no-lock")
            transaction.write_text(".anchor/state.txt", "unsafe\n")
            with self.assertRaises(ProjectLockError):
                transaction.commit()

    def test_transaction_rejects_reserved_paths_escape_and_id_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = TransactionManager(root)
            transaction = manager.begin(transaction_id="safe-id")
            with self.assertRaises(AnchorError):
                transaction.write_text("../outside.txt", "outside")
            with self.assertRaises(TransactionError):
                transaction.write_text(".anchor/events.jsonl", "bypass outbox")

            with ProjectLock(root):
                first = manager.begin(transaction_id="same-id", command="one")
                first.write_text(".anchor/state.txt", "one\n")
                first.commit()

                conflict = manager.begin(transaction_id="same-id", command="two")
                conflict.write_text(".anchor/state.txt", "two\n")
                with self.assertRaises(TransactionError):
                    conflict.commit()

    @staticmethod
    def _events(root: Path) -> list[dict[str, object]]:
        path = root / ".anchor" / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


if __name__ == "__main__":
    unittest.main()
