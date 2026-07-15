from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anchorloop.project import AnchorError, AnchorProject


BRIEF = {
    "outcome": "Deliver the bounded acceptance behavior.",
    "scope": "Only the active implementation path.",
    "constraints": "Keep the public interface stable.",
    "invariant": "The accepted operation has no duplicate effect.",
    "uncertainty": "The retry boundary may be incorrect.",
}


class ActualDiffRiskTests(unittest.TestCase):
    def _git(self, root: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    def _init_git(self, root: Path) -> None:
        self._git(root, "init", "--quiet")
        self._git(root, "config", "user.name", "AnchorLoop Tests")
        self._git(
            root,
            "config",
            "user.email",
            "anchorloop-tests@example.invalid",
        )
        self._git(root, "config", "commit.gpgsign", "false")

    def _commit_file(
        self,
        root: Path,
        relative: str,
        content: str = "baseline\n",
    ) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._git(root, "add", "--", relative)
        self._git(
            root,
            "commit",
            "--quiet",
            "-m",
            f"baseline {relative}",
        )
        return path

    def _plan(
        self,
        project: AnchorProject,
        *,
        mode: str,
        override: str | None = None,
    ) -> None:
        project.plan_task(
            "Persist the retry attempt before delivery.",
            mode=mode,
            task_type="feature",
            approach="Write retry state before calling the destination.",
            rejected_alternative=(
                "An in-memory counter loses state after restart."
            ),
            primary_risk="A retry could acknowledge one event twice.",
            verification_strategy=(
                "Exercise duplicate and transient-failure scenarios."
            ),
            human_artifact=(
                "Acceptance case: one delivery acknowledgement per event."
            ),
            comprehension=(
                "Persisted state prevents duplicate acknowledgement."
            ),
            rollback_mitigation=(
                "Restore the previous delivery state before accepting "
                "another event."
                if mode == "CAREFUL"
                else None
            ),
            mode_override_reason=override,
            by="Ada Engineer",
        )

    def _implementing_project(
        self,
        root: Path,
        *,
        mode: str = "STANDARD",
        override: str | None = None,
    ) -> AnchorProject:
        project = AnchorProject.at(root)
        project.apply_setup("add")
        project.start_task("Protect the actual implementation diff")
        project.record_brief(by="Ada Engineer", values=BRIEF)
        self._plan(project, mode=mode, override=override)
        project.approve_task("Ada Engineer")
        project.transition("implement")
        return project

    def test_standard_review_blocks_all_git_path_sources(self) -> None:
        cases = (
            ("auth/permissions.py", "unstaged"),
            ("migrations/0042.sql", "deleted"),
            ("package-lock.json", "staged"),
        )
        for relative, state in cases:
            with (
                self.subTest(path=relative, state=state),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                self._init_git(root)
                path = self._commit_file(root, relative)
                project = self._implementing_project(root)

                if state == "unstaged":
                    path.write_text("changed\n", encoding="utf-8")
                elif state == "deleted":
                    path.unlink()
                else:
                    path.write_text("changed\n", encoding="utf-8")
                    self._git(root, "add", "--", relative)

                before = path.read_bytes() if path.exists() else None
                with self.assertRaisesRegex(
                    AnchorError,
                    re.escape(relative),
                ) as raised:
                    project.transition("review")
                self.assertIn(
                    "anchor revise --target plan --reason "
                    '"Actual diff introduced CAREFUL risk paths."',
                    str(raised.exception),
                )
                task = json.loads(
                    project.active_task_path.read_text(encoding="utf-8")
                )
                self.assertEqual(task["state"], "implementing")
                self.assertNotIn("quality", task)
                self.assertEqual(
                    path.read_bytes() if path.exists() else None,
                    before,
                )

    def test_careful_review_allows_risk_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            project = self._implementing_project(root, mode="CAREFUL")
            for relative in (
                "auth/permissions.py",
                "migrations/0042.sql",
                "package-lock.json",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("changed\n", encoding="utf-8")

            reviewed = project.transition("review")
            self.assertEqual(reviewed["state"], "review_ready")

    def test_staged_rename_reports_the_sensitive_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "auth/permissions.py")
            project = self._implementing_project(root)
            self._git(root, "mv", "--", "auth/permissions.py", "harmless.py")

            with self.assertRaisesRegex(
                AnchorError,
                r"auth/permissions\.py",
            ):
                project.transition("review")
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "implementing")

    def test_git_inspection_failure_blocks_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            project = self._implementing_project(root)

            with (
                mock.patch("anchorloop.quality._git_bytes", return_value=None),
                self.assertRaisesRegex(AnchorError, "Cannot evaluate the actual Git diff safely"),
            ):
                project.transition("review")
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "implementing")

    def test_non_git_project_blocks_lower_mode_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._implementing_project(root)

            with self.assertRaisesRegex(
                AnchorError,
                "Cannot evaluate the actual Git diff safely",
            ):
                project.transition("review")
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "implementing")

    def test_nested_project_reports_paths_relative_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self._init_git(repository)
            root = repository / "nested-project"
            self._commit_file(repository, "nested-project/auth/permissions.py")
            project = self._implementing_project(root)
            risky = root / "auth" / "permissions.py"
            risky.write_text("changed\n", encoding="utf-8")

            with self.assertRaisesRegex(
                AnchorError,
                r"auth/permissions\.py",
            ) as raised:
                project.transition("review")
            self.assertNotIn("nested-project/auth", str(raised.exception))
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "implementing")

    def test_preapproved_path_override_still_requires_a_revision_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            override = "Engineer reviewed actual diff risk path: auth/permissions.py"
            project = self._implementing_project(root, override=override)
            risky = root / "auth" / "permissions.py"
            risky.parent.mkdir(parents=True)
            risky.write_text("changed\n", encoding="utf-8")

            with self.assertRaisesRegex(AnchorError, r"auth/permissions\.py"):
                project.transition("review")
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "implementing")

    def test_lower_mode_explicit_override_is_approval_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            project = self._implementing_project(root)
            risky = root / "auth" / "permissions.py"
            risky.parent.mkdir(parents=True)
            risky.write_text("changed\n", encoding="utf-8")

            with self.assertRaises(AnchorError):
                project.transition("review")
            project.revise_task(
                target="plan",
                reason="Actual diff introduced CAREFUL risk paths.",
            )
            override = (
                "Engineer reviewed actual diff risk path: "
                "auth/permissions.py"
            )
            self._plan(
                project,
                mode="STANDARD",
                override=override,
            )
            approved = project.approve_task("Ada Engineer")
            self.assertEqual(
                approved["plan"]["mode_recommendation"]["override_reason"],
                override,
            )
            self.assertEqual(
                approved["approval"]["plan_digest"],
                project._document_digest(approved["plan"]),
            )

            project.transition("implement")
            reviewed = project.transition("review")
            self.assertEqual(reviewed["state"], "review_ready")

    def test_anchor_only_changes_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            project = self._implementing_project(root)
            ignored = root / ".anchor" / "auth" / "permissions.py"
            ignored.parent.mkdir(parents=True)
            ignored.write_text("managed state\n", encoding="utf-8")

            reviewed = project.transition("review")
            self.assertEqual(reviewed["state"], "review_ready")

    def test_risk_added_after_review_blocks_precommit_without_quality(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            project = self._implementing_project(root)
            reviewed = project.transition("review")
            self.assertEqual(reviewed["state"], "review_ready")

            risky = root / "payments" / "new_gateway.py"
            risky.parent.mkdir(parents=True)
            risky.write_text("ENABLED = False\n", encoding="utf-8")
            before = risky.read_bytes()

            with self.assertRaisesRegex(
                AnchorError,
                r"payments/new_gateway\.py",
            ):
                project.precommit()
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "review_ready")
            self.assertNotIn("quality", task)
            self.assertEqual(risky.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
