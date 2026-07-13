from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from anchorloop.cli import main
from anchorloop.project import AnchorError, AnchorProject
from anchorloop.skill_install import SkillInstaller


def _run(root: Path, *arguments: str) -> int:
    return main([*arguments, "--path", str(root)])


def _approved_task(root: Path) -> None:
    assert _run(root, "add", "--apply") == 0
    assert _run(root, "start", "Protect workflow integrity") == 0
    assert (
        _run(
            root,
            "brief",
            "--by",
            "Ada Engineer",
            "--outcome",
            "Preserve the reviewed workflow.",
            "--scope",
            "Only the named task.",
            "--constraints",
            "Keep the public CLI compatible.",
            "--invariant",
            "The acceptance scenario succeeds.",
            "--uncertainty",
            "Production traffic is unknown.",
        )
        == 0
    )
    assert _run(root, "plan", "--summary", "Implement the smallest safe change.") == 0
    assert _run(root, "approve", "--by", "Ada Engineer") == 0


class IntegrityRegressionTests(unittest.TestCase):
    def test_changed_brief_requires_a_new_brief_record_before_replanning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _approved_task(root)
            task_path = root / ".anchor" / "tasks" / "active.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["brief"]["outcome"] = "A manually edited outcome needs a new record."
            task_path.write_text(json.dumps(task), encoding="utf-8")

            self.assertEqual(_run(root, "implement"), 2)
            invalidated = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(invalidated["state"], "briefing")
            self.assertNotIn("brief_record", invalidated)
            self.assertEqual(_run(root, "plan", "--summary", "Bypass the brief."), 2)

    def test_changed_brief_record_invalidates_task_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _approved_task(root)
            task_path = root / ".anchor" / "tasks" / "active.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["brief_record"]["by"] = "Someone else"
            task_path.write_text(json.dumps(task), encoding="utf-8")

            self.assertEqual(_run(root, "implement"), 2)
            invalidated = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(invalidated["state"], "briefing")
            self.assertNotIn("brief_record", invalidated)

    def test_blocked_precommit_can_return_to_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _approved_task(root)
            self.assertEqual(_run(root, "implement"), 0)
            self.assertEqual(_run(root, "review"), 0)
            (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")

            self.assertEqual(_run(root, "precommit"), 2)
            self.assertEqual(
                _run(root, "revise", "--target", "implement", "--reason", "Fix the blocked syntax check."),
                0,
            )
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(task["state"], "implementing")

    def test_review_ready_and_implementing_tasks_can_return_to_planning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _approved_task(root)
            self.assertEqual(_run(root, "implement"), 0)
            self.assertEqual(_run(root, "review"), 0)
            self.assertEqual(
                _run(root, "revise", "--target", "plan", "--reason", "The implementation approach is wrong."),
                0,
            )
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(task["state"], "planned")

            self.assertEqual(_run(root, "plan", "--summary", "Use the corrected approach."), 0)
            self.assertEqual(_run(root, "approve", "--by", "Ada Engineer"), 0)
            self.assertEqual(_run(root, "implement"), 0)
            self.assertEqual(
                _run(root, "revise", "--target", "plan", "--reason", "Revisit the active implementation."),
                0,
            )
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(task["state"], "planned")

    def test_rules_cannot_self_supersede_or_reactivate_a_superseded_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(_run(root, "add", "--apply"), 0)
            project = AnchorProject.at(root)
            project.approve_rule("baseline-security-v1", by="Ada Engineer")
            replacement = project.propose_rule("security", "Use the reviewed replacement security rule.")
            project.approve_rule(replacement["id"], by="Ada Engineer")

            with self.assertRaises(AnchorError):
                project.supersede_rule(
                    old_rule_id="baseline-security-v1",
                    new_rule_id="baseline-security-v1",
                    by="Ada Engineer",
                    reason="Invalid self replacement.",
                )

            project.supersede_rule(
                old_rule_id="baseline-security-v1",
                new_rule_id=replacement["id"],
                by="Ada Engineer",
                reason="Use the reviewed replacement.",
            )
            with self.assertRaises(AnchorError):
                project.supersede_rule(
                    old_rule_id=replacement["id"],
                    new_rule_id="baseline-security-v1",
                    by="Ada Engineer",
                    reason="Invalid cycle.",
                )

            active_path = root / ".anchor" / "rules" / "active.json"
            active = json.loads(active_path.read_text(encoding="utf-8"))
            active["rules"]["security"] = "baseline-security-v1"
            active_path.write_text(json.dumps(active), encoding="utf-8")
            doctor = project.doctor()
            active_rule_check = next(check for check in doctor["checks"] if check["name"] == "active-rules")
            self.assertEqual(active_rule_check["status"], "failed")

    def test_installation_status_detects_modified_owned_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                _run(root, "install", "--project", "--platform", "codex", "--apply"),
                0,
            )
            skill = root / ".codex" / "skills" / "anchorloop" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\nLocal change.\n", encoding="utf-8")

            status = SkillInstaller(root).installation_status(platform="codex", project_scoped=True)
            self.assertEqual(status["integrity"], "modified")
            self.assertFalse(status["up_to_date"])

    def test_installation_status_detects_missing_owned_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                _run(root, "install", "--project", "--platform", "agents", "--apply"),
                0,
            )
            skill = root / ".agents" / "skills" / "anchorloop" / "SKILL.md"
            skill.unlink()

            status = SkillInstaller(root).installation_status(platform="agents", project_scoped=True)
            self.assertEqual(status["integrity"], "modified")
            self.assertFalse(status["up_to_date"])
