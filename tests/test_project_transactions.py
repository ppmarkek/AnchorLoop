from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from anchorloop.cli import main
from anchorloop.project import AnchorError, AnchorProject
from anchorloop.project_lock import ProjectLock
from anchorloop.transaction import TransactionManager


class _CrashDuringRuleApproval(TransactionManager):
    def _apply_operation(self, operation: dict[str, object]) -> bool:
        super()._apply_operation(operation)
        os._exit(41)


def _crash_rule_approval(root: str) -> None:
    import anchorloop.project as project_module

    project_module.TransactionManager = _CrashDuringRuleApproval
    AnchorProject.at(root).approve_rule("baseline-code-quality-v1", by="Crash fixture")


class ProjectTransactionIntegrationTests(unittest.TestCase):
    def test_process_crash_during_rule_approval_recovers_every_owned_file_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            AnchorProject.at(root).apply_setup("add")
            context = multiprocessing.get_context("spawn")
            process = context.Process(target=_crash_rule_approval, args=(str(root),))
            process.start()
            process.join(timeout=15)
            self.assertEqual(process.exitcode, 41)

            self.assertEqual(main(["doctor", "--repair", "--path", str(root)]), 0)
            active = json.loads(
                (root / ".anchor" / "rules" / "active.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                active["rules"]["code-quality"],
                "baseline-code-quality-v1",
            )
            self.assertTrue(
                (root / ".anchor" / "rules" / "approved" / "baseline-code-quality-v1.json").is_file()
            )
            self.assertFalse(
                (root / ".anchor" / "rules" / "proposals" / "baseline-code-quality-v1.json").exists()
            )
            events = [
                json.loads(line)
                for line in (root / ".anchor" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            approvals = [
                event
                for event in events
                if event.get("type") == "rule.approved"
                and event.get("rule_id") == "baseline-code-quality-v1"
            ]
            self.assertEqual(len(approvals), 1)
            self.assertEqual(
                list((root / ".anchor" / "transactions" / "pending").glob("*.json")),
                [],
            )
            self.assertEqual(list((root / ".anchor" / "outbox").glob("*.json")), [])

    def test_parallel_start_creates_exactly_one_active_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            AnchorProject.at(root).apply_setup("add")

            def start(title: str) -> str:
                try:
                    return AnchorProject.at(root).start_task(title)["id"]
                except AnchorError as error:
                    return f"error:{error}"

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(start, ["First", "Second"]))

            successes = [result for result in results if not result.startswith("error:")]
            failures = [result for result in results if result.startswith("error:")]
            self.assertEqual(len(successes), 1)
            self.assertEqual(len(failures), 1)
            active = json.loads((root / ".anchor" / "tasks" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(active["id"], successes[0])
            events = [
                json.loads(line)
                for line in (root / ".anchor" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(sum(event["type"] == "task.started" for event in events), 1)

    def test_parallel_rule_approvals_do_not_lose_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            AnchorProject.at(root).apply_setup("add")

            def approve(rule_id: str) -> str:
                return AnchorProject.at(root).approve_rule(rule_id, by="Ada Engineer")["id"]

            with ThreadPoolExecutor(max_workers=2) as executor:
                approved = set(
                    executor.map(
                        approve,
                        ["baseline-code-quality-v1", "baseline-security-v1"],
                    )
                )

            self.assertEqual(approved, {"baseline-code-quality-v1", "baseline-security-v1"})
            active = json.loads((root / ".anchor" / "rules" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(active["rules"]["code-quality"], "baseline-code-quality-v1")
            self.assertEqual(active["rules"]["security"], "baseline-security-v1")

    def test_event_log_symlink_is_rejected_before_task_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            AnchorProject.at(root).apply_setup("add")
            event_log = root / ".anchor" / "events.jsonl"
            event_log.unlink()
            sentinel = root / "sentinel.jsonl"
            sentinel.write_text("outside\n", encoding="utf-8")
            try:
                os.symlink(sentinel, event_log)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlink creation unavailable: {error}")

            with self.assertRaises(AnchorError):
                AnchorProject.at(root).start_task("Must not partially start")

            self.assertFalse((root / ".anchor" / "tasks" / "active.json").exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside\n")
            pending = root / ".anchor" / "transactions" / "pending"
            self.assertEqual(list(pending.glob("*.json")), [])

    def test_doctor_repair_recovers_interrupted_initial_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ProjectLock(root, purpose="test.prepare-interrupted-setup"):
                manager = TransactionManager(root)
                manager._ensure_directories()
                transaction = manager.begin(
                    transaction_id="interrupted-initial-setup",
                    command="project.setup",
                )
                transaction.write_json(
                    root / ".anchor" / "config.json",
                    {"schema_version": 1, "name": "recovered", "ruleset_version": None},
                )
                record = manager._record_for(transaction)
                manager._write_json(manager._pending_path(transaction.transaction_id), record)

            self.assertFalse((root / ".anchor" / "config.json").exists())
            self.assertEqual(main(["doctor", "--repair", "--path", str(root)]), 0)
            self.assertTrue((root / ".anchor" / "config.json").is_file())
            self.assertEqual(list((root / ".anchor" / "transactions" / "pending").glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
