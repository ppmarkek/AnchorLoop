from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from anchorloop.cli import main
from anchorloop.quality import workspace_fingerprint


def record_brief(root: Path) -> int:
    return main(
        [
            "brief",
            "--by",
            "Ada Engineer",
            "--outcome",
            "Deliver the requested behavior.",
            "--scope",
            "Only the named task; no unrelated refactor.",
            "--constraints",
            "Keep the public interface compatible.",
            "--invariant",
            "The acceptance scenario succeeds.",
            "--uncertainty",
            "Production traffic shape is unknown.",
            "--path",
            str(root),
        ]
    )


def record_plan(root: Path, summary: str) -> int:
    return main(
        [
            "plan",
            "--summary",
            summary,
            "--mode",
            "STANDARD",
            "--task-type",
            "feature",
            "--approach",
            summary,
            "--alternative",
            "A broader rewrite was rejected as unnecessary.",
            "--risk",
            "The acceptance invariant could regress.",
            "--verification",
            "Run the acceptance scenario and deterministic checks.",
            "--human-artifact",
            "Acceptance case: the requested behavior succeeds without unrelated changes.",
            "--comprehension",
            "Prediction: the smallest scoped change preserves the public interface.",
            "--by",
            "Ada Engineer",
            "--path",
            str(root),
        ]
    )


class AnchorCliTests(unittest.TestCase):
    def test_add_preview_discloses_gitignore_changes_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                result = main(["add", "--path", str(root)])

            self.assertEqual(result, 0)
            self.assertIn(
                "Will create or append managed cache and recovery rules in .gitignore and .anchor/.gitignore",
                output.getvalue(),
            )
            self.assertIn("Detected project markers: none.", output.getvalue())
            self.assertFalse((root / ".gitignore").exists())
            self.assertFalse((root / ".anchor").exists())

            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
            detected_output = io.StringIO()
            with contextlib.redirect_stdout(detected_output):
                self.assertEqual(main(["add", "--path", str(root)]), 0)
            self.assertIn("Detected project markers: python, node.", detected_output.getvalue())

    def test_add_apply_creates_portable_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result = main(["add", "--path", str(root), "--apply"])

            self.assertEqual(result, 0)
            self.assertTrue((root / ".anchor" / "config.json").is_file())
            self.assertTrue((root / ".anchor" / "protocol" / "anchor-protocol.json").is_file())
            self.assertTrue((root / ".anchor" / "next-action.md").is_file())
            self.assertTrue((root / ".anchor" / "rules" / "proposals" / "baseline-code-quality-v1.json").is_file())

    def test_init_name_creates_a_new_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)

            self.assertEqual(main(["init", "new-anchor-project", "--path", str(parent), "--apply"]), 0)

            self.assertTrue((parent / "new-anchor-project" / ".anchor" / "config.json").is_file())

    def test_task_requires_approval_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Retry webhooks", "--path", str(root)]), 0)

            self.assertEqual(main(["implement", "--path", str(root)]), 2)
            self.assertEqual(record_plan(root, "Retry with bounded backoff."), 2)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Retry with bounded backoff."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            self.assertEqual(main(["implement", "--path", str(root)]), 0)

            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(task["state"], "implementing")
            self.assertEqual(task["approval"]["by"], "Ada Engineer")
            self.assertTrue(task["ruleset"]["version"].startswith("ruleset-"))

    def test_task_approval_is_invalidated_when_pinned_artifacts_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Pin the approved task", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Implement the approved change."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)

            task_path = root / ".anchor" / "tasks" / "active.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["plan"]["summary"] = "A locally edited plan must be approved again."
            task_path.write_text(json.dumps(task), encoding="utf-8")

            self.assertEqual(main(["implement", "--path", str(root)]), 2)
            task = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["state"], "planned")
            self.assertNotIn("approval", task)
            self.assertIn("plan", task["approval_invalidations"][-1]["changed_artifacts"])

            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["ruleset"]["version"] = "ruleset-manually-edited"
            task_path.write_text(json.dumps(task), encoding="utf-8")

            self.assertEqual(main(["implement", "--path", str(root)]), 2)
            task = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["state"], "planned")
            self.assertIn("ruleset", task["approval_invalidations"][-1]["changed_artifacts"])

    def test_revision_cannot_bypass_a_changed_task_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Protect a revised task", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Use the approved approach."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            for action in ("implement", "review", "precommit"):
                self.assertEqual(main([action, "--path", str(root)]), 0)

            task_path = root / ".anchor" / "tasks" / "active.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["plan"]["summary"] = "An altered plan must not reopen implementation."
            task_path.write_text(json.dumps(task), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "revise",
                        "--target",
                        "implement",
                        "--reason",
                        "Attempt to continue after a changed plan.",
                        "--path",
                        str(root),
                    ]
                ),
                2,
            )
            task = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["state"], "planned")
            self.assertNotIn("approval", task)

    def test_rules_remain_inactive_until_engineer_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)

            self.assertEqual(
                main(
                    [
                        "rules",
                        "propose",
                        "structure",
                        "Features may import only public module entry points.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            proposal = next((root / ".anchor" / "rules" / "proposals").glob("rule-structure-*.json"))
            proposal_data = json.loads(proposal.read_text())

            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        proposal_data["id"],
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            self.assertTrue((root / ".anchor" / "rules" / "approved" / proposal.name).is_file())
            self.assertFalse(proposal.exists())

    def test_precommit_blocks_invalid_python_before_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Validate quality", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Run the local quality gate."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            for action in ("implement", "review"):
                self.assertEqual(main([action, "--path", str(root)]), 0)

            (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")

            self.assertEqual(main(["precommit", "--path", str(root)]), 2)
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(task["state"], "review_ready")
            self.assertEqual(task["quality"][-1]["status"], "blocked")

    def test_approved_security_rule_blocks_a_possible_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        "baseline-security-v1",
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            self.assertEqual(main(["start", "Protect configuration", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Use configured secret storage."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            for action in ("implement", "review"):
                self.assertEqual(main([action, "--path", str(root)]), 0)

            (root / "settings.py").write_text('api_key = "abcdefghijk"\n', encoding="utf-8")

            self.assertEqual(main(["precommit", "--path", str(root)]), 2)
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(task["quality"][-1]["checks"][1]["status"], "failed")

    def test_task_uses_the_ruleset_approved_with_its_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Pin rules", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Keep this ruleset snapshot."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        "baseline-security-v1",
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            for action in ("implement", "review"):
                self.assertEqual(main([action, "--path", str(root)]), 0)

            (root / "settings.py").write_text('api_key = "abcdefghijk"\n', encoding="utf-8")

            self.assertEqual(main(["precommit", "--path", str(root)]), 0)
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(task["quality"][-1]["checks"][1]["status"], "not-run")

    def test_task_closes_only_after_precommit_and_human_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Ship a small change", "--path", str(root)]), 0)

            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Implement the smallest safe change."), 0)
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
                        "Acceptance scenario completed successfully.",
                        "--recall",
                        "The acceptance invariant is the reason this plan is safe.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            self.assertEqual(main(["close", "--path", str(root)]), 0)

            self.assertFalse((root / ".anchor" / "tasks" / "active.json").exists())
            closed_tasks = list((root / ".anchor" / "tasks" / "closed").glob("*.json"))
            self.assertEqual(len(closed_tasks), 1)
            self.assertEqual(json.loads(closed_tasks[0].read_text())["state"], "closed")

    def test_rule_approve_rejects_path_traversal_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            config_path = root / ".anchor" / "config.json"
            original_config = config_path.read_text(encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        "../../config",
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                2,
            )
            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        str(config_path),
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                2,
            )
            self.assertEqual(config_path.read_text(encoding="utf-8"), original_config)

    def test_failed_verification_can_return_to_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Repair behaviour", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Implement the smallest repair."), 0)
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
                        "fail",
                        "--reason",
                        "The acceptance scenario still fails.",
                        "--recall",
                        "The observed failure disproves the planned behavior.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "revise",
                        "--target",
                        "implement",
                        "--reason",
                        "Fix the failing scenario within the approved scope.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(task["state"], "implementing")
            self.assertEqual(task["revisions"][-1]["target"], "implement")

    def test_code_change_after_precommit_invalidates_quality_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Protect checked code", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Run the quality gate."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            for action in ("implement", "review", "precommit"):
                self.assertEqual(main([action, "--path", str(root)]), 0)

            (root / "changed_after_quality.py").write_text("value = 1\n", encoding="utf-8")
            self.assertEqual(
                main(
                    [
                        "verify",
                        "--by",
                        "Ada Engineer",
                        "--result",
                        "pass",
                        "--reason",
                        "The original acceptance scenario passed.",
                        "--recall",
                        "The changed workspace invalidates the earlier evidence.",
                        "--path",
                        str(root),
                    ]
                ),
                2,
            )
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(task["state"], "review_ready")
            self.assertTrue(task["quality_invalidations"])

    def test_git_workspace_fingerprint_ignores_anchor_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tracked.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "tracked.py"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=AnchorLoop Test",
                    "-c",
                    "user.email=anchorloop@example.test",
                    "commit",
                    "-m",
                    "Initial fixture",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )

            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Verify Git snapshot", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Check the Git fingerprint."), 0)
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
                        "The unchanged Git fixture passed.",
                        "--recall",
                        "Anchor state is excluded from the materialized evidence.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(task["state"], "verified")

    def test_git_commit_does_not_invalidate_identical_materialized_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracked = root / "tracked.py"
            tracked.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "tracked.py"], cwd=root, check=True, capture_output=True)
            identity = [
                "-c",
                "user.name=AnchorLoop Test",
                "-c",
                "user.email=anchorloop@example.test",
            ]
            subprocess.run(
                ["git", *identity, "commit", "-m", "Initial fixture"],
                cwd=root,
                check=True,
                capture_output=True,
            )

            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Commit after quality", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Verify the materialized tree."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            self.assertEqual(main(["implement", "--path", str(root)]), 0)
            tracked.write_text("value = 2\n", encoding="utf-8")
            self.assertEqual(main(["review", "--path", str(root)]), 0)
            self.assertEqual(main(["precommit", "--path", str(root)]), 0)
            before = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())[
                "quality"
            ][-1]["workspace_fingerprint"]

            subprocess.run(["git", "add", "tracked.py"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["git", *identity, "commit", "-m", "Materialize checked change"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            self.assertEqual(
                main(
                    [
                        "verify",
                        "--by",
                        "Ada Engineer",
                        "--result",
                        "pass",
                        "--reason",
                        "The checked content is unchanged by the commit.",
                        "--recall",
                        "A metadata-only commit does not change the checked files.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            after = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(after["state"], "verified")
            self.assertEqual(before["digest"], before["content_digest"])

    def test_git_submodule_worktree_changes_invalidate_materialized_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            child = root / "vendor" / "child"
            child.mkdir(parents=True)
            identity = [
                "-c",
                "user.name=AnchorLoop Test",
                "-c",
                "user.email=anchorloop@example.test",
            ]
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "init"], cwd=child, check=True, capture_output=True)
            (child / "module.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "module.py"], cwd=child, check=True, capture_output=True)
            subprocess.run(
                ["git", *identity, "commit", "-m", "Child fixture"],
                cwd=child,
                check=True,
                capture_output=True,
            )
            child_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=child,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                [
                    "git",
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"160000,{child_head},vendor/child",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", *identity, "commit", "-m", "Root fixture"],
                cwd=root,
                check=True,
                capture_output=True,
            )

            before = workspace_fingerprint(root)
            (root / "vendor" / "child" / "module.py").write_text("value = 2\n", encoding="utf-8")
            after = workspace_fingerprint(root)

            self.assertNotEqual(before["digest"], after["digest"])
            self.assertEqual(after["source"], "git-materialized")

            # A porcelain status only says that the submodule is dirty. The
            # fingerprint must still distinguish two different dirty trees.
            dirty_before = after
            (root / "vendor" / "child" / "module.py").write_text(
                "value = 3\n", encoding="utf-8"
            )
            dirty_after = workspace_fingerprint(root)
            self.assertNotEqual(dirty_before["digest"], dirty_after["digest"])

    def test_legacy_quality_evidence_returns_to_review_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Recover legacy task", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Refresh quality evidence."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            for action in ("implement", "review", "precommit"):
                self.assertEqual(main([action, "--path", str(root)]), 0)

            task_path = root / ".anchor" / "tasks" / "active.json"
            task = json.loads(task_path.read_text())
            task["quality"][-1].pop("workspace_fingerprint")
            task_path.write_text(json.dumps(task), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "verify",
                        "--by",
                        "Ada Engineer",
                        "--result",
                        "pass",
                        "--reason",
                        "This should require fresh quality evidence.",
                        "--recall",
                        "Legacy evidence has no trustworthy content fingerprint.",
                        "--path",
                        str(root),
                    ]
                ),
                2,
            )
            repaired = json.loads(task_path.read_text())
            self.assertEqual(repaired["state"], "review_ready")
            self.assertTrue(repaired["quality_invalidations"])

    def test_rule_approve_rejects_a_tampered_document_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            proposal_path = root / ".anchor" / "rules" / "proposals" / "baseline-security-v1.json"
            proposal = json.loads(proposal_path.read_text())
            proposal["id"] = "baseline-code-quality-v1"
            proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        "baseline-security-v1",
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                2,
            )
            self.assertFalse((root / ".anchor" / "rules" / "approved" / "baseline-security-v1.json").exists())

    def test_changed_approved_rule_document_blocks_task_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        "baseline-security-v1",
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            approved_path = root / ".anchor" / "rules" / "approved" / "baseline-security-v1.json"
            approved = json.loads(approved_path.read_text())
            approved["wording"] = "A manually changed rule should not retain prior approval."
            approved_path.write_text(json.dumps(approved), encoding="utf-8")

            self.assertEqual(main(["start", "Pin exact rule wording", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(record_plan(root, "Use the current ruleset."), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 2)
            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(task["state"], "planned")

    def test_approved_rule_needs_explicit_supersede_to_replace_active_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        "baseline-security-v1",
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "rules",
                        "propose",
                        "security",
                        "Require a second security review for credential rotation.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            proposal = next((root / ".anchor" / "rules" / "proposals").glob("rule-security-*.json"))
            new_rule_id = json.loads(proposal.read_text(encoding="utf-8"))["id"]
            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        new_rule_id,
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            active_path = root / ".anchor" / "rules" / "active.json"
            self.assertEqual(json.loads(active_path.read_text())["rules"]["security"], "baseline-security-v1")

            self.assertEqual(
                main(
                    [
                        "rules",
                        "supersede",
                        "baseline-security-v1",
                        new_rule_id,
                        "--by",
                        "Ada Engineer",
                        "--reason",
                        "The new credential-rotation policy replaces the baseline.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            self.assertEqual(json.loads(active_path.read_text())["rules"]["security"], new_rule_id)

    def test_legacy_rule_can_be_migrated_only_by_explicit_supersession(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        "baseline-security-v1",
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            old_rule_path = root / ".anchor" / "rules" / "approved" / "baseline-security-v1.json"
            old_rule = json.loads(old_rule_path.read_text(encoding="utf-8"))
            old_rule.pop("approved_document_digest")
            old_rule_path.write_text(json.dumps(old_rule), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "rules",
                        "propose",
                        "security",
                        "Require a documented rotation review.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            proposal = next((root / ".anchor" / "rules" / "proposals").glob("rule-security-*.json"))
            new_rule_id = json.loads(proposal.read_text(encoding="utf-8"))["id"]
            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        new_rule_id,
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "rules",
                        "supersede",
                        "baseline-security-v1",
                        new_rule_id,
                        "--by",
                        "Ada Engineer",
                        "--reason",
                        "Migrate the legacy rule to an integrity-protected document.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            active = json.loads((root / ".anchor" / "rules" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(active["rules"]["security"], new_rule_id)

    def test_migrating_one_of_multiple_legacy_rules_keeps_audit_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            for rule_id in ("baseline-security-v1", "baseline-code-quality-v1"):
                self.assertEqual(
                    main(
                        [
                            "rules",
                            "approve",
                            rule_id,
                            "--by",
                            "Ada Engineer",
                            "--path",
                            str(root),
                        ]
                    ),
                    0,
                )
                rule_path = root / ".anchor" / "rules" / "approved" / f"{rule_id}.json"
                rule = json.loads(rule_path.read_text(encoding="utf-8"))
                rule.pop("approved_document_digest")
                rule_path.write_text(json.dumps(rule), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "rules",
                        "propose",
                        "security",
                        "Require an integrity-protected security rule.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            proposal = next((root / ".anchor" / "rules" / "proposals").glob("rule-security-*.json"))
            new_rule_id = json.loads(proposal.read_text(encoding="utf-8"))["id"]
            self.assertEqual(
                main(
                    [
                        "rules",
                        "approve",
                        new_rule_id,
                        "--by",
                        "Ada Engineer",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "rules",
                        "supersede",
                        "baseline-security-v1",
                        new_rule_id,
                        "--by",
                        "Ada Engineer",
                        "--reason",
                        "Migrate one legacy rule without losing the remaining migration state.",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )

            active = json.loads((root / ".anchor" / "rules" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(active["rules"]["security"], new_rule_id)
            config = json.loads((root / ".anchor" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["ruleset_integrity"], "migration-required")
            events = [
                json.loads(line)
                for line in (root / ".anchor" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(any(event.get("type") == "rule.superseded" for event in events))

    def test_project_skill_install_is_previewed_and_uninstalls_only_owned_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / ".agents" / "skills" / "anchorloop"
            quoted_root = root / "O'Reilly project"

            preview_output = io.StringIO()
            with contextlib.redirect_stdout(preview_output):
                self.assertEqual(
                    main(
                        [
                            "install",
                            "--project",
                            "--platform",
                            "codex",
                            "--path",
                            str(quoted_root),
                        ]
                    ),
                    0,
                )
            self.assertIn(
                f"From {quoted_root.resolve()}, apply with: anchor install --project --platform codex --apply",
                preview_output.getvalue(),
            )
            self.assertNotIn("--path", preview_output.getvalue())
            force_preview = io.StringIO()
            with contextlib.redirect_stdout(force_preview):
                self.assertEqual(
                    main(["uninstall", "--project", "--force", "--path", str(root)]),
                    0,
                )
            self.assertIn(
                f"From {root.resolve()}, apply with: anchor uninstall --project --platform agents --apply --force",
                force_preview.getvalue(),
            )
            self.assertEqual(main(["install", "--project", "--path", str(root)]), 0)
            self.assertFalse(destination.exists())
            self.assertEqual(main(["install", "--project", "--apply", "--path", str(root)]), 0)
            self.assertTrue((destination / "SKILL.md").is_file())
            self.assertTrue((destination / "references" / "workflow.md").is_file())
            self.assertIn("anchor status", (destination / "SKILL.md").read_text(encoding="utf-8"))
            marker_path = destination / ".anchorloop-skill.json"
            self.assertTrue(marker_path.is_file())

            codex_destination = quoted_root / ".codex" / "skills" / "anchorloop"
            self.assertEqual(
                main(
                    [
                        "install",
                        "--project",
                        "--platform",
                        "codex",
                        "--skill-runtime",
                        "npx",
                        "--npx-package",
                        "anchorloop@0.1.0",
                        "--apply",
                        "--path",
                        str(quoted_root),
                    ]
                ),
                0,
            )
            codex_skill = codex_destination / "SKILL.md"
            self.assertTrue(codex_skill.is_file())
            self.assertIn(
                "npx --yes anchorloop@0.1.0 status",
                codex_skill.read_text(encoding="utf-8"),
            )
            codex_marker = json.loads((codex_destination / ".anchorloop-skill.json").read_text())
            self.assertEqual(codex_marker["runtime"], "npx")
            self.assertEqual(codex_marker["npx_package"], "anchorloop@0.1.0")

            legacy_content = "stale packaged asset\n"
            legacy_asset = destination / "legacy.md"
            legacy_asset.write_bytes(legacy_content.encode("utf-8"))
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["files"].append(
                {
                    "path": "legacy.md",
                    "sha256": f"sha256:{hashlib.sha256(legacy_content.encode('utf-8')).hexdigest()}",
                }
            )
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
            self.assertEqual(main(["install", "--project", "--apply", "--path", str(root)]), 0)
            self.assertFalse(legacy_asset.exists())

            note = destination / "user-note.txt"
            note.write_text("keep me\n", encoding="utf-8")
            skill_path = destination / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8") + "\nLocal note.\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["uninstall", "--project", "--apply", "--path", str(root)]), 2)
            self.assertTrue(skill_path.exists())
            self.assertEqual(
                main(["uninstall", "--project", "--apply", "--force", "--path", str(root)]),
                0,
            )
            self.assertTrue(note.exists())
            self.assertFalse(skill_path.exists())
            self.assertFalse((destination / ".anchorloop-skill.json").exists())

    def test_npx_skill_runtime_requires_a_pinned_package_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            self.assertEqual(
                main(
                    [
                        "install",
                        "--project",
                        "--platform",
                        "codex",
                        "--skill-runtime",
                        "npx",
                        "--npx-package",
                        "anchorloop@latest",
                        "--apply",
                        "--path",
                        str(root),
                    ]
                ),
                2,
            )
            self.assertFalse((root / ".codex" / "skills" / "anchorloop").exists())

    def test_doctor_reports_corrupt_state_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            (root / ".anchor" / "config.json").write_text("{not valid json", encoding="utf-8")

            self.assertEqual(main(["doctor", "--path", str(root)]), 0)

    def test_setup_recovers_missing_scaffold_file_and_agent_status_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            protocol = root / ".anchor" / "protocol" / "ANCHOR.md"
            protocol.unlink()

            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertTrue(protocol.exists())
            self.assertEqual(main(["agent", "status", "--path", str(root)]), 0)
            self.assertFalse((root / ".anchor" / "agents" / "capabilities.json").exists())
            self.assertEqual(main(["agent", "setup", "portable", "--path", str(root)]), 0)
            self.assertEqual(main(["agent", "setup", "portable", "--apply", "--path", str(root)]), 0)
            adapter_path = root / ".anchor" / "agents" / "adapters" / "portable.json"
            self.assertTrue(adapter_path.is_file())
            self.assertIn("revise", json.loads(adapter_path.read_text())["commands"])


if __name__ == "__main__":
    unittest.main()
