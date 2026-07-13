from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from anchorloop.cli import main


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


class AnchorCliTests(unittest.TestCase):
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
            self.assertEqual(main(["plan", "--summary", "Retry with bounded backoff.", "--path", str(root)]), 2)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(main(["plan", "--summary", "Retry with bounded backoff.", "--path", str(root)]), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            self.assertEqual(main(["implement", "--path", str(root)]), 0)

            task = json.loads((root / ".anchor" / "tasks" / "active.json").read_text())
            self.assertEqual(task["state"], "implementing")
            self.assertEqual(task["approval"]["by"], "Ada Engineer")
            self.assertTrue(task["ruleset"]["version"].startswith("ruleset-"))

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

            self.assertEqual(main(["rules", "approve", proposal_data["id"], "--path", str(root)]), 0)
            self.assertTrue((root / ".anchor" / "rules" / "approved" / proposal.name).is_file())
            self.assertFalse(proposal.exists())

    def test_precommit_blocks_invalid_python_before_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(main(["start", "Validate quality", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(main(["plan", "--summary", "Run the local quality gate.", "--path", str(root)]), 0)
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
            self.assertEqual(main(["rules", "approve", "baseline-security-v1", "--path", str(root)]), 0)
            self.assertEqual(main(["start", "Protect configuration", "--path", str(root)]), 0)
            self.assertEqual(record_brief(root), 0)
            self.assertEqual(main(["plan", "--summary", "Use configured secret storage.", "--path", str(root)]), 0)
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
            self.assertEqual(main(["plan", "--summary", "Keep this ruleset snapshot.", "--path", str(root)]), 0)
            self.assertEqual(main(["approve", "--by", "Ada Engineer", "--path", str(root)]), 0)
            self.assertEqual(main(["rules", "approve", "baseline-security-v1", "--path", str(root)]), 0)
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
            self.assertEqual(main(["plan", "--summary", "Implement the smallest safe change.", "--path", str(root)]), 0)
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
            self.assertTrue((root / ".anchor" / "agents" / "adapters" / "portable.json").is_file())


if __name__ == "__main__":
    unittest.main()
