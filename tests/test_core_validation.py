from __future__ import annotations

import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path

from anchorloop.cli import _print_experiment_report
from anchorloop.project import AnchorError, AnchorProject
from tests.git_fixture import init_git_repository


BRIEF = {
    "outcome": "Deliver the bounded acceptance behavior.",
    "scope": "Only the active delivery path.",
    "constraints": "Keep the public interface stable.",
    "invariant": "The accepted operation has no duplicate effect.",
    "uncertainty": "The retry boundary may be incorrect.",
}


class CoreValidationTests(unittest.TestCase):
    def _project_in_briefing(self, root: Path) -> AnchorProject:
        project = AnchorProject.at(root)
        project.apply_setup("add")
        project.start_task("Validate project inputs")
        return project

    def _project_ready_for_verification(
        self,
        root: Path,
        *,
        mode: str = "STANDARD",
    ) -> AnchorProject:
        init_git_repository(root)
        project = self._project_in_briefing(root)
        project.record_brief(by="Ada Engineer", values=BRIEF)
        project.plan_task(
            "Persist the retry attempt before delivery.",
            mode=mode,
            task_type="feature",
            approach="Write retry state before calling the destination.",
            rejected_alternative="An in-memory counter loses state after restart.",
            primary_risk="A retry could acknowledge one event twice.",
            verification_strategy="Exercise duplicate and transient-failure scenarios.",
            human_artifact="Acceptance case: one delivery acknowledgement per event.",
            comprehension="Persisted state is the invariant that prevents duplicate acknowledgement.",
            rollback_mitigation=(
                "Restore the previous delivery state before accepting another event."
                if mode == "CAREFUL"
                else None
            ),
            by="Ada Engineer",
        )
        project.approve_task("Ada Engineer")
        project.transition("implement")
        project.transition("review")
        project.precommit()
        return project

    def _closed_project(
        self,
        root: Path,
        *,
        mode: str = "STANDARD",
    ) -> tuple[AnchorProject, dict[str, object], Path]:
        project = self._project_ready_for_verification(root, mode=mode)
        project.verify_task(
            by="Ada Engineer",
            result="pass",
            reason="The documented acceptance scenario passed.",
            recall="Persisted retry state prevents duplicate acknowledgement.",
        )
        closed = project.transition("close")
        closed_path = root / ".anchor" / "tasks" / "closed" / f"{closed['id']}.json"
        return project, closed, closed_path

    def test_public_record_brief_requires_exact_complete_text_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_in_briefing(root)
            active_path = root / ".anchor" / "tasks" / "active.json"
            before = active_path.read_bytes()

            with self.assertRaisesRegex(AnchorError, "fields must be exact"):
                project.record_brief(by="Ada Engineer", values={"outcome": "Only one field."})
            self.assertEqual(active_path.read_bytes(), before)

            malformed = {**BRIEF, "unexpected": "value"}
            with self.assertRaisesRegex(AnchorError, "fields must be exact"):
                project.record_brief(by="Ada Engineer", values=malformed)
            self.assertEqual(active_path.read_bytes(), before)

            non_text = {**BRIEF, "scope": 42}
            with self.assertRaisesRegex(AnchorError, "must be text"):
                project.record_brief(by="Ada Engineer", values=non_text)  # type: ignore[arg-type]
            self.assertEqual(active_path.read_bytes(), before)

    def test_public_verify_rejects_invalid_result_and_metric_types_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_ready_for_verification(root)
            active_path = root / ".anchor" / "tasks" / "active.json"
            before = active_path.read_bytes()
            common = {
                "by": "Ada Engineer",
                "result": "pass",
                "reason": "The documented acceptance scenario passed.",
                "recall": "Persisted retry state prevents duplicate acknowledgement.",
            }

            with self.assertRaisesRegex(AnchorError, "Verification result must be one of"):
                project.verify_task(**{**common, "result": "passed"})
            with self.assertRaisesRegex(AnchorError, "Verification result must be one of"):
                project.verification_preview(
                    result="passed",
                    reason=common["reason"],
                    recall=common["recall"],
                )
            self.assertEqual(active_path.read_bytes(), before)

            invalid_metric_cases = (
                {"agent_turns": "3"},
                {"input_tokens": 1.5},
                {"output_tokens": True},
                {"active_minutes": math.inf},
                {"agent_provider": "openai"},
            )
            for metrics in invalid_metric_cases:
                with self.subTest(metrics=metrics), self.assertRaises(AnchorError):
                    project.verify_task(**common, **metrics)  # type: ignore[arg-type]
                self.assertEqual(active_path.read_bytes(), before)

    def test_current_task_approval_attribution_is_integrity_protected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_ready_for_verification(root)
            active_path = root / ".anchor" / "tasks" / "active.json"
            task = json.loads(active_path.read_text(encoding="utf-8"))
            task["approval"]["by"] = "Mallory"
            active_path.write_text(json.dumps(task), encoding="utf-8")

            with self.assertRaisesRegex(AnchorError, "approval record digest"):
                project.status()

    def test_newly_closed_legacy_shaped_task_receives_close_integrity_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_git_repository(root)
            project = self._project_in_briefing(root)
            project.record_brief(by="Ada Engineer", values=BRIEF)
            project.plan_task(
                "Persist the retry attempt before delivery.",
                mode="STANDARD",
                task_type="feature",
                approach="Write retry state before calling the destination.",
                rejected_alternative="An in-memory counter loses state after restart.",
                primary_risk="A retry could acknowledge one event twice.",
                verification_strategy="Exercise duplicate and transient-failure scenarios.",
                human_artifact="Acceptance case: one delivery acknowledgement per event.",
                comprehension="Persisted state prevents duplicate acknowledgement.",
                by="Ada Engineer",
            )
            active_path = root / ".anchor" / "tasks" / "active.json"
            legacy_shaped = json.loads(active_path.read_text(encoding="utf-8"))
            legacy_shaped.pop("schema_version")
            active_path.write_text(json.dumps(legacy_shaped), encoding="utf-8")

            preview = project.task_approval_preview()
            project.approve_task(
                "Ada Engineer",
                provenance="interactive-tty",
                interactive_confirmed=True,
                expected_subject_digest=preview["subject_digest"],
            )
            project.transition("implement")
            project.transition("review")
            project.precommit()
            project.verify_task(
                by="Ada Engineer",
                result="pass",
                reason="The documented acceptance scenario passed.",
                recall="Persisted retry state prevents duplicate acknowledgement.",
            )
            closed = project.transition("close")
            self.assertEqual(closed["schema_version"], 2)
            self.assertIn("close_digest", closed)

            closed_path = root / ".anchor" / "tasks" / "closed" / f"{closed['id']}.json"
            forged = json.loads(closed_path.read_text(encoding="utf-8"))
            forged.pop("close_digest")
            shift = timedelta(days=365)
            forged["created_at"] = (
                datetime.fromisoformat(forged["created_at"]) + shift
            ).isoformat()
            forged["metrics"]["closed_at"] = (
                datetime.fromisoformat(forged["metrics"]["closed_at"]) + shift
            ).isoformat()
            closed_path.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(AnchorError, "close digest"):
                project.experiment_report()

    def test_auto_risk_uses_russian_path_and_explicit_rule_signals(self) -> None:
        russian_brief = {
            **BRIEF,
            "scope": "Миграция платёжных данных и изменение авторизации.",
        }
        with tempfile.TemporaryDirectory() as directory:
            project = self._project_in_briefing(Path(directory))
            project.record_brief(by="Ada Engineer", values=russian_brief)
            planned = project.plan_task(
                "Deliver the migration with an explicit rollback.",
                mode="AUTO",
                task_type="feature",
                approach="Apply the migration in a bounded deployment step.",
                rejected_alternative="A silent schema rewrite was rejected as unsafe.",
                primary_risk="Payment records could become inconsistent.",
                verification_strategy="Exercise the migration and authorization scenario.",
                human_artifact="Acceptance case: existing payment records remain valid.",
                comprehension="The migration must preserve authorization and payment invariants.",
                rollback_mitigation="Restore the previous schema before accepting traffic.",
                by="Ada Engineer",
            )
            self.assertEqual(planned["mode"], "CAREFUL")
            self.assertIn("migration", planned["plan"]["mode_recommendation"]["reason"])

        path_brief = {**BRIEF, "scope": "Изменить src/auth/session.py и infra/terraform/main.tf."}
        mode, reason = AnchorProject._recommended_mode("docs", path_brief)
        self.assertEqual(mode, "CAREFUL")
        self.assertIn("path", reason)

        rule_brief = {**BRIEF, "scope": "Rename a local display label."}
        mode, reason = AnchorProject._recommended_mode(
            "chore",
            rule_brief,
            approved_rules={
                "security": {
                    "wording": "CAREFUL is required for any change covered by this approved rule."
                }
            },
        )
        self.assertEqual(mode, "CAREFUL")
        self.assertIn("approved security rule", reason)

    def test_legacy_careful_recall_record_remains_usable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_ready_for_verification(root, mode="CAREFUL")
            project.verify_task(
                by="Ada Engineer",
                result="pass",
                reason="The documented acceptance scenario passed.",
                recall="Persisted retry state prevents duplicate acknowledgement.",
            )
            active_path = root / ".anchor" / "tasks" / "active.json"
            legacy = json.loads(active_path.read_text(encoding="utf-8"))
            legacy_due_at = datetime.now(UTC) - timedelta(minutes=1)
            comprehension = legacy["comprehension"]
            comprehension.pop("recall_delay_hours")
            comprehension["recall_due_at"] = legacy_due_at.isoformat()
            legacy.pop("schema_version")
            legacy["verification"].pop("subject_digest")
            legacy["verification"].pop("reported_metrics")
            legacy["verification"].pop("comprehension_digest")
            legacy["verification"].pop("record_digest")
            legacy["approval"].pop("record_digest")
            legacy["approval"].update(
                project._task_approval_digests(project._task_approval_subject(legacy))
            )
            active_path.write_text(json.dumps(legacy), encoding="utf-8")

            self.assertEqual(project.status()["active_task"]["state"], "verified")
            closed = project.transition("close")
            task_id = closed["id"]
            closed_path = root / ".anchor" / "tasks" / "closed" / f"{task_id}.json"
            self.assertNotIn("recall_delay_hours", closed["comprehension"])
            self.assertEqual(closed["comprehension"]["recall_due_at"], legacy_due_at.isoformat())
            self.assertEqual(project.status()["pending_recalls"][0]["status"], "due")
            self.assertEqual(project.doctor(strict=True)["status"], "ok")

            tampered = json.loads(closed_path.read_text(encoding="utf-8"))
            tampered["comprehension"]["recall_due_at"] = (
                legacy_due_at - timedelta(hours=1)
            ).isoformat()
            closed_path.write_text(json.dumps(tampered), encoding="utf-8")
            self.assertEqual(project.status()["pending_recalls"][0]["status"], "invalid")
            self.assertEqual(project.doctor(strict=True)["status"], "attention")
            closed_path.write_text(json.dumps(closed), encoding="utf-8")

            recalled = project.record_delayed_recall(
                task_id=task_id,
                by="Ada Engineer",
                response="The retry boundary remains the key trade-off.",
                score=4,
            )
            self.assertEqual(recalled["comprehension"]["delayed_recall"]["score"], 4)

            legacy_observations = json.loads(
                closed_path.read_text(encoding="utf-8")
            )
            legacy_observations["comprehension"]["delayed_recall"].pop(
                "record_digest"
            )
            closed_path.write_text(
                json.dumps(legacy_observations),
                encoding="utf-8",
            )
            project.record_post_completion_outcome(
                task_id=task_id,
                by="Ada Engineer",
                defects_found=1,
                rollback=False,
                corrective_refactor=True,
                notes="A legacy follow-up observation remains readable.",
            )
            legacy_observations = json.loads(
                closed_path.read_text(encoding="utf-8")
            )
            legacy_observations["post_completion_outcomes"][-1].pop(
                "record_digest"
            )
            closed_path.write_text(
                json.dumps(legacy_observations),
                encoding="utf-8",
            )

            report = project.experiment_report()
            row = report["tasks"][0]
            self.assertEqual(
                row["delayed_recall_integrity"],
                "legacy-unverified",
            )
            self.assertEqual(
                row["latest_outcome_integrity"],
                "legacy-unverified",
            )
            self.assertEqual(row["legacy_unverified_observations"], 2)
            self.assertEqual(
                report["summary"]["legacy_unverified_observations"],
                2,
            )
            csv_output = io.StringIO()
            with redirect_stdout(csv_output):
                _print_experiment_report(report, output_format="csv")
            csv_text = csv_output.getvalue()
            header = csv_text.splitlines()[0]
            self.assertIn("delayed_recall_integrity", header)
            self.assertIn("latest_outcome_integrity", header)
            self.assertIn("legacy_unverified_observations", header)
            self.assertEqual(csv_text.count("legacy-unverified"), 2)

    def test_current_post_close_records_require_record_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_ready_for_verification(root, mode="CAREFUL")
            project.verify_task(
                by="Ada Engineer",
                result="pass",
                reason="The documented acceptance scenario passed.",
                recall="Persisted retry state prevents duplicate acknowledgement.",
            )
            closed = project.transition("close")
            closed_path = (
                root / ".anchor" / "tasks" / "closed" / f"{closed['id']}.json"
            )
            due_at = closed["comprehension"]["recall_due_at"]
            closed["comprehension"]["delayed_recall"] = {
                "statement": "The retry boundary remains the key trade-off.",
                "score": 4,
                "by": "Ada Engineer",
                "due_at": due_at,
                "recorded_at": due_at,
                "delay_seconds": 0.0,
            }
            closed_path.write_text(json.dumps(closed), encoding="utf-8")
            with self.assertRaisesRegex(
                AnchorError,
                "Protected delayed recall records require a record digest",
            ):
                project.experiment_report()

            closed["comprehension"].pop("delayed_recall")
            closed["post_completion_outcomes"] = [
                {
                    "at": closed["metrics"]["closed_at"],
                    "by": "Ada Engineer",
                    "defects_found": 0,
                    "rollback": False,
                    "corrective_refactor": False,
                    "notes": "No follow-up defect was observed.",
                    "provenance": "reported-post-completion",
                }
            ]
            closed_path.write_text(json.dumps(closed), encoding="utf-8")
            with self.assertRaisesRegex(
                AnchorError,
                "Protected post-completion outcome records require a record digest",
            ):
                project.experiment_report()

    def test_schema_v2_without_post_close_discriminator_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, closed, closed_path = self._closed_project(root)
            recorded = project.record_post_completion_outcome(
                task_id=str(closed["id"]),
                by="Ada Engineer",
                defects_found=0,
                rollback=False,
                corrective_refactor=False,
                notes="Historical schema-v2 observation.",
            )
            legacy = json.loads(json.dumps(recorded))
            legacy.pop("post_close_integrity")
            outcome = legacy["post_completion_outcomes"][0]
            for field in (
                "record_digest",
                "record_type",
                "task_id",
                "sequence",
                "previous_digest",
            ):
                outcome.pop(field)
            legacy["close_digest"] = project._closed_task_digest(legacy)
            closed_path.write_text(json.dumps(legacy), encoding="utf-8")

            report = project.experiment_report()
            self.assertEqual(report["tasks"][0]["latest_outcome_integrity"], "legacy-unverified")
            self.assertEqual(report["summary"]["legacy_unverified_observations"], 1)

    def test_post_close_chain_rejects_replay_reorder_delete_and_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, closed, closed_path = self._closed_project(root)
            for index in range(2):
                project.record_post_completion_outcome(
                    task_id=str(closed["id"]),
                    by="Ada Engineer",
                    defects_found=index,
                    rollback=False,
                    corrective_refactor=False,
                    notes=f"Follow-up observation {index + 1}.",
                )
            pristine = json.loads(closed_path.read_text(encoding="utf-8"))

            def replay_from_another_task(task: dict[str, object]) -> None:
                record = task["post_completion_outcomes"][1]  # type: ignore[index]
                record["task_id"] = "al-20000101-deadbe"
                record["record_digest"] = project._record_digest(record)
                task["post_close_integrity"]["head_digest"] = record["record_digest"]  # type: ignore[index]

            tamper_cases = {
                "replay": replay_from_another_task,
                "reorder": lambda task: task["post_completion_outcomes"].reverse(),
                "delete": lambda task: task["post_completion_outcomes"].pop(0),
                "duplicate": lambda task: task["post_completion_outcomes"].__setitem__(
                    1, json.loads(json.dumps(task["post_completion_outcomes"][0]))
                ),
            }
            for name, tamper in tamper_cases.items():
                with self.subTest(name=name):
                    candidate = json.loads(json.dumps(pristine))
                    tamper(candidate)
                    closed_path.write_text(json.dumps(candidate), encoding="utf-8")
                    with self.assertRaises(AnchorError):
                        project.experiment_report()
            closed_path.write_text(json.dumps(pristine), encoding="utf-8")
            self.assertEqual(
                project.experiment_report()["tasks"][0]["latest_outcome_integrity"],
                "chain-verified",
            )

    def test_delayed_recall_record_rejects_digest_preserving_type_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_ready_for_verification(root, mode="CAREFUL")
            project.verify_task(
                by="Ada Engineer",
                result="pass",
                reason="The documented acceptance scenario passed.",
                recall="Persisted retry state prevents duplicate acknowledgement.",
            )
            active_path = root / ".anchor" / "tasks" / "active.json"
            legacy = json.loads(active_path.read_text(encoding="utf-8"))
            due_at = datetime.now(UTC) - timedelta(minutes=1)
            legacy["comprehension"].pop("recall_delay_hours")
            legacy["comprehension"]["recall_due_at"] = due_at.isoformat()
            legacy.pop("schema_version")
            for field in (
                "subject_digest",
                "reported_metrics",
                "comprehension_digest",
                "record_digest",
            ):
                legacy["verification"].pop(field)
            legacy["approval"].pop("record_digest")
            legacy["approval"].update(
                project._task_approval_digests(project._task_approval_subject(legacy))
            )
            active_path.write_text(json.dumps(legacy), encoding="utf-8")

            closed = project.transition("close")
            closed_path = root / ".anchor" / "tasks" / "closed" / f"{closed['id']}.json"
            recorded = project.record_delayed_recall(
                task_id=closed["id"],
                by="Ada Engineer",
                response="The retry boundary remains the key trade-off.",
                score=2,
            )
            recall_record = recorded["comprehension"]["delayed_recall"]
            self.assertRegex(recall_record["record_digest"], r"^sha256:[0-9a-f]{64}$")

            tampered = json.loads(closed_path.read_text(encoding="utf-8"))
            tampered["comprehension"]["delayed_recall"]["score"] = 5
            closed_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(AnchorError, "delayed recall record digest"):
                project.experiment_report()

    def test_post_completion_outcome_rejects_digest_preserving_type_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_ready_for_verification(root)
            project.verify_task(
                by="Ada Engineer",
                result="pass",
                reason="The documented acceptance scenario passed.",
                recall="Persisted retry state prevents duplicate acknowledgement.",
            )
            closed = project.transition("close")
            closed_path = root / ".anchor" / "tasks" / "closed" / f"{closed['id']}.json"
            recorded = project.record_post_completion_outcome(
                task_id=closed["id"],
                by="Ada Engineer",
                defects_found=0,
                rollback=False,
                corrective_refactor=False,
                notes="No follow-up defect was observed.",
            )
            outcome = recorded["post_completion_outcomes"][-1]
            self.assertRegex(outcome["record_digest"], r"^sha256:[0-9a-f]{64}$")

            tampered = json.loads(closed_path.read_text(encoding="utf-8"))
            tampered["post_completion_outcomes"][-1]["defects_found"] = 9
            closed_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(AnchorError, "post-completion outcome record digest"):
                project.experiment_report()

    def test_task_schema_rejects_manually_malformed_brief_before_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_in_briefing(root)
            active_path = root / ".anchor" / "tasks" / "active.json"
            task = json.loads(active_path.read_text(encoding="utf-8"))
            task["brief"] = {"unexpected": "field"}
            active_path.write_text(json.dumps(task), encoding="utf-8")

            with self.assertRaisesRegex(AnchorError, "fields must be exact"):
                project.record_brief(by="Ada Engineer", values=BRIEF)

    def test_task_schema_requires_standard_ownership_evidence_before_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_in_briefing(root)
            project.record_brief(by="Ada Engineer", values=BRIEF)
            project.plan_task(
                "Persist the retry attempt before delivery.",
                mode="STANDARD",
                task_type="feature",
                approach="Write retry state before calling the destination.",
                rejected_alternative="An in-memory counter loses state after restart.",
                primary_risk="A retry could acknowledge one event twice.",
                verification_strategy="Exercise duplicate and transient-failure scenarios.",
                human_artifact="Acceptance case: one acknowledgement per event.",
                comprehension="Persisted state prevents duplicate acknowledgement.",
                by="Ada Engineer",
            )
            active_path = root / ".anchor" / "tasks" / "active.json"
            baseline = json.loads(active_path.read_text(encoding="utf-8"))
            for field in ("human_artifact", "comprehension"):
                with self.subTest(field=field):
                    tampered = json.loads(json.dumps(baseline))
                    if field == "human_artifact":
                        tampered[field] = None
                    else:
                        tampered[field]["baseline"] = None
                    active_path.write_text(json.dumps(tampered), encoding="utf-8")
                    with self.assertRaisesRegex(AnchorError, "ownership evidence"):
                        project.approve_task("Ada Engineer")
            active_path.write_text(json.dumps(baseline), encoding="utf-8")

    def test_closed_task_public_methods_reject_non_text_task_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = AnchorProject.at(Path(directory))
            project.apply_setup("add")
            for task_id in (None, 1, b"task", Path("task")):
                with self.subTest(task_id=task_id):
                    with self.assertRaisesRegex(AnchorError, "Invalid AnchorLoop task ID"):
                        project.record_delayed_recall(
                            task_id=task_id,  # type: ignore[arg-type]
                            by="Ada Engineer",
                            response="Recall",
                            score=3,
                        )
                    with self.assertRaisesRegex(AnchorError, "Invalid AnchorLoop task ID"):
                        project.record_post_completion_outcome(
                            task_id=task_id,  # type: ignore[arg-type]
                            by="Ada Engineer",
                            defects_found=0,
                            rollback=False,
                            corrective_refactor=False,
                            notes="No issue.",
                        )

    def test_task_schema_requires_approval_and_quality_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project_ready_for_verification(root)
            active_path = root / ".anchor" / "tasks" / "active.json"
            baseline = json.loads(active_path.read_text(encoding="utf-8"))
            cases = (
                ("approval", "approval record"),
                ("quality", "passing quality evidence"),
            )
            for field, message in cases:
                with self.subTest(field=field):
                    tampered = json.loads(json.dumps(baseline))
                    tampered.pop(field)
                    active_path.write_text(json.dumps(tampered), encoding="utf-8")
                    with self.assertRaisesRegex(AnchorError, message):
                        project.verify_task(
                            by="Ada Engineer",
                            result="pass",
                            reason="The documented acceptance scenario passed.",
                            recall="Persisted state prevents duplicate acknowledgement.",
                        )
            active_path.write_text(json.dumps(baseline), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
