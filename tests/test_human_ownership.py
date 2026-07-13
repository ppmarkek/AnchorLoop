from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from anchorloop.cli import main
from anchorloop.project import AnchorError, AnchorProject


def _brief(root: Path) -> None:
    result = main(
        [
            "brief",
            "--by",
            "Ada Engineer",
            "--outcome",
            "Deliver the acceptance behavior.",
            "--scope",
            "Only the active task.",
            "--constraints",
            "Keep the public interface stable.",
            "--invariant",
            "The acceptance scenario succeeds without duplicate effects.",
            "--uncertainty",
            "The retry boundary may be wrong.",
            "--path",
            str(root),
        ]
    )
    if result != 0:
        raise AssertionError(f"brief failed with exit code {result}")


def _structured_plan(root: Path, *, mode: str = "STANDARD") -> list[str]:
    return [
        "plan",
        "--summary",
        "Persist bounded retry state.",
        "--mode",
        mode,
        "--task-type",
        "feature",
        "--approach",
        "Store retry state beside the delivery record.",
        "--alternative",
        "An in-memory queue was rejected because restart loses state.",
        "--risk",
        "A retry may acknowledge one event twice.",
        "--verification",
        "Run duplicate-event and transient-failure scenarios.",
        "--human-artifact",
        "Acceptance case: one event is acknowledged at most once.",
        "--comprehension",
        "Prediction: persisting the attempt before dispatch prevents duplicate acknowledgement.",
        "--rollback-mitigation",
        "Disable retries and restore the previous dispatcher configuration.",
        "--by",
        "Ada Engineer",
        "--path",
        str(root),
    ]


class HumanOwnershipTests(unittest.TestCase):
    def test_empty_experiment_report_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            report = AnchorProject.at(root).experiment_report()
            self.assertEqual(report["summary"]["closed_tasks"], 0)
            self.assertEqual(report["tasks"], [])

    def test_standard_mode_requires_structured_engineer_owned_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Own the approach", "--path", str(root)]), 0)
            _brief(root)

            self.assertEqual(
                main(
                    [
                        "plan",
                        "--summary",
                        "An incomplete standard plan.",
                        "--mode",
                        "STANDARD",
                        "--path",
                        str(root),
                    ]
                ),
                2,
            )
            self.assertEqual(main(_structured_plan(root)), 0)

            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(task["mode"], "STANDARD")
            self.assertEqual(task["task_type"], "feature")
            self.assertEqual(task["plan"]["primary_risk"], "A retry may acknowledge one event twice.")
            self.assertEqual(task["human_artifact"]["by"], "Ada Engineer")
            self.assertIn("Prediction", task["comprehension"]["baseline"]["statement"])

    def test_standard_verification_requires_recall_and_records_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Measure understanding", "--path", str(root)]), 0)
            _brief(root)
            self.assertEqual(main(_structured_plan(root)), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            for action in ("implement", "review", "precommit"):
                self.assertEqual(main([action, "--path", str(root)]), 0)

            base_verify = [
                "verify",
                "--by",
                "Ada Engineer",
                "--result",
                "pass",
                "--reason",
                "The acceptance case passed.",
                "--path",
                str(root),
            ]
            self.assertEqual(main(base_verify), 2)
            self.assertEqual(
                main(
                    [
                        *base_verify[:-2],
                        "--recall",
                        "The persisted attempt is the invariant that prevents duplicate acknowledgement.",
                        "--agent-turns",
                        "4",
                        "--input-tokens",
                        "1200",
                        "--output-tokens",
                        "300",
                        "--active-minutes",
                        "8.5",
                        "--agent-provider",
                        "openai",
                        "--agent-model",
                        "gpt-5-codex",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(task["state"], "verified")
            self.assertEqual(task["metrics"]["agent_turns"], 4)
            self.assertEqual(task["metrics"]["agent_provider"], "openai")
            self.assertEqual(task["metrics"]["agent_model"], "gpt-5-codex")
            self.assertEqual(task["metrics"]["provenance"], "reported-at-verification")
            self.assertEqual(task["comprehension"]["verification_check"]["by"], "Ada Engineer")
            task_id = task["id"]
            self.assertEqual(main(["close", "--path", str(root)]), 0)
            outcome = [
                "outcome",
                "--task",
                task_id,
                "--by",
                "Ada Engineer",
                "--defects",
                "1",
                "--rollback",
                "no",
                "--corrective-refactor",
                "yes",
                "--notes",
                "One post-completion edge case required a bounded refactor.",
                "--path",
                str(root),
            ]
            self.assertEqual(main(outcome), 0)
            report = AnchorProject.at(root).experiment_report()
            self.assertEqual(report["summary"]["closed_tasks"], 1)
            self.assertEqual(report["summary"]["tasks_with_outcome_observation"], 1)
            self.assertEqual(report["tasks"][0]["agent_provider"], "openai")
            self.assertEqual(report["tasks"][0]["defects_found"], 1)
            self.assertTrue(report["tasks"][0]["corrective_refactor"])

            csv_output = io.StringIO()
            with redirect_stdout(csv_output):
                self.assertEqual(
                    main(["report", "--format", "csv", "--path", str(root)]),
                    0,
                )
            self.assertIn("task_id,title,mode,task_type", csv_output.getvalue())
            self.assertIn(task_id, csv_output.getvalue())

    def test_careful_mode_schedules_delayed_recall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Plan a risky migration", "--path", str(root)]), 0)
            _brief(root)
            self.assertEqual(main(_structured_plan(root, mode="CAREFUL")), 0)

            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text(encoding="utf-8"))
            self.assertIsNotNone(task["comprehension"]["recall_due_at"])
            task_id = task["id"]
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            for action in ("implement", "review", "precommit"):
                self.assertEqual(main([action, "--path", str(root)]), 0)
            self.assertEqual(
                main(
                    [
                        "verify",
                        "--by",
                        "Ada Engineer",
                        "--result",
                        "pass",
                        "--reason",
                        "The migration scenario passed.",
                        "--recall",
                        "The rollback disables retries and restores the previous dispatcher.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            self.assertEqual(main(["close", "--path", str(root)]), 0)

            closed_path = root / ".anchor" / "tasks" / "closed" / f"{task_id}.json"
            closed = json.loads(closed_path.read_text(encoding="utf-8"))
            due_at = datetime.fromisoformat(closed["comprehension"]["recall_due_at"])
            status = AnchorProject.at(root).status()
            self.assertEqual(status["pending_recalls"][0]["task_id"], task_id)
            self.assertEqual(status["pending_recalls"][0]["status"], "scheduled")
            self.assertIn(f"recall --task {task_id}", status["pending_recalls"][0]["command"])
            self.assertIn(task_id, status["next_action"])

            tampered = json.loads(json.dumps(closed))
            tampered["comprehension"]["recall_due_at"] = (
                datetime.now(UTC) - timedelta(minutes=1)
            ).isoformat()
            closed_path.write_text(json.dumps(tampered), encoding="utf-8")
            self.assertEqual(
                main(
                    [
                        "recall",
                        "--task",
                        task_id,
                        "--by",
                        "Ada Engineer",
                        "--response",
                        "A forged due date must not unlock recall.",
                        "--score",
                        "5",
                        "--path",
                        str(root),
                    ]
                ),
                2,
            )
            closed_path.write_text(json.dumps(closed), encoding="utf-8")

            class AfterRecallDue(datetime):
                @classmethod
                def now(cls, tz: object = None) -> datetime:
                    return due_at + timedelta(minutes=1)

            with mock.patch("anchorloop.project.datetime", AfterRecallDue):
                self.assertEqual(
                    main(
                        [
                            "recall",
                            "--task",
                            task_id,
                            "--by",
                            "Ada Engineer",
                            "--response",
                            "Persisting the attempt before dispatch is the key invariant.",
                            "--score",
                            "4",
                            "--path",
                            str(root),
                        ]
                    ),
                    0,
                )
            recalled = json.loads(closed_path.read_text(encoding="utf-8"))
            self.assertEqual(recalled["comprehension"]["delayed_recall"]["score"], 4)
            self.assertEqual(AnchorProject.at(root).status()["pending_recalls"], [])

    def test_changed_human_artifact_invalidates_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Protect ownership evidence", "--path", str(root)]), 0)
            _brief(root)
            self.assertEqual(main(_structured_plan(root)), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)

            task_path = root / ".anchor" / "tasks" / "active.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["human_artifact"]["content"] = "Changed after approval."
            task_path.write_text(json.dumps(task), encoding="utf-8")

            self.assertEqual(main(["implement", "--path", str(root)]), 2)
            task = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["state"], "planned")
            self.assertIn("ownership", task["approval_invalidations"][-1]["changed_artifacts"])

    def test_interactive_approval_is_bound_to_displayed_subject(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Bind approval", "--path", str(root)]), 0)
            _brief(root)
            self.assertEqual(main(_structured_plan(root)), 0)
            project = AnchorProject.at(root)
            preview = project.task_approval_preview()

            task_path = root / ".anchor" / "tasks" / "active.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["plan"]["summary"] = "Changed after the subject was displayed."
            task_path.write_text(json.dumps(task), encoding="utf-8")

            with self.assertRaisesRegex(AnchorError, "subject changed"):
                project.approve_task(
                    "Ada Engineer",
                    provenance="interactive-tty",
                    interactive_confirmed=True,
                    expected_subject_digest=preview["subject_digest"],
                )


if __name__ == "__main__":
    unittest.main()
