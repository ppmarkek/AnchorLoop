from __future__ import annotations

import json
import math
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
