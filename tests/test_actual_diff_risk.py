from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anchorloop.project import AnchorError, AnchorProject
from anchorloop.quality import GitInspectionError, workspace_fingerprint


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

    def _git_output(self, root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

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
        active_security: bool = False,
    ) -> AnchorProject:
        project = AnchorProject.at(root)
        project.apply_setup("add")
        if active_security:
            project.approve_rule("baseline-security-v1", by="Ada Engineer")
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

    def test_committed_auth_after_approval_blocks_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            self._commit_file(
                root,
                "auth/permissions.py",
                "ALLOW_ADMIN = False\n",
            )

            with self.assertRaisesRegex(
                AnchorError,
                r"auth/permissions\.py",
            ):
                project.transition("review")
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "implementing")
            self.assertNotIn("quality", task)

    def test_git_replace_cannot_hide_committed_sensitive_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            baseline = task["change_baseline"]["head"]
            self._commit_file(
                root,
                "auth/permissions.py",
                "ALLOW_ADMIN = False\n",
            )
            current_tree = self._git_output(root, "rev-parse", "HEAD^{tree}")
            replacement = self._git_output(root, "commit-tree", current_tree)
            self._git(root, "replace", baseline, replacement)

            with self.assertRaisesRegex(
                AnchorError,
                r"auth/permissions\.py",
            ):
                project.transition("review")

    def test_inherited_git_environment_cannot_divert_diff_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            self._init_git(root)
            self._commit_file(root, "README.md")
            clean = base / "clean"
            self._git(
                base,
                "-c",
                "protocol.file.allow=always",
                "clone",
                "--quiet",
                str(root),
                str(clean),
            )
            project = self._implementing_project(root)
            self._commit_file(
                root,
                "auth/permissions.py",
                "ALLOW_ADMIN = False\n",
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "GIT_DIR": str(clean / ".git"),
                        "GIT_WORK_TREE": str(clean),
                    },
                    clear=False,
                ),
                self.assertRaisesRegex(
                    AnchorError,
                    r"auth/permissions\.py",
                ),
            ):
                project.transition("review")

    def test_legacy_git_grafts_block_required_diff_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            head = self._git_output(root, "rev-parse", "HEAD")
            grafts = root / ".git" / "info" / "grafts"
            grafts.parent.mkdir(parents=True, exist_ok=True)
            grafts.write_text(f"{head}\n", encoding="utf-8")

            with self.assertRaisesRegex(AnchorError, "grafts"):
                project.transition("review")

    def test_committed_python_syntax_error_blocks_precommit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            self._commit_file(root, "src/broken.py", "def broken(:\n")
            (root / "src" / "broken.py").write_text(
                "def broken():\n    return None\n",
                encoding="utf-8",
            )
            project.transition("review")

            with self.assertRaisesRegex(AnchorError, "Pre-commit is blocked"):
                project.precommit()
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["quality"][-1]["status"], "blocked")
            self.assertTrue(
                any(
                    finding["location"].startswith("src/broken.py")
                    for finding in task["quality"][-1]["findings"]
                )
            )

    def test_committed_secret_blocks_precommit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root, active_security=True)
            self._commit_file(
                root,
                "src/config.py",
                'API_KEY = "abcdefgh-secret-value"\n',
            )
            (root / "src" / "config.py").write_text(
                "API_KEY = None\n",
                encoding="utf-8",
            )
            project.transition("review")

            with self.assertRaisesRegex(AnchorError, "Pre-commit is blocked"):
                project.precommit()
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertTrue(
                any(
                    finding["category"] == "secret"
                    and finding["location"].startswith("src/config.py")
                    for finding in task["quality"][-1]["findings"]
                )
            )

    def test_staged_secret_cannot_be_masked_by_safe_unstaged_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root, active_security=True)
            config = root / "src" / "config.py"
            config.parent.mkdir(parents=True)
            config.write_text('API_KEY = "abcdefgh-secret-value"\n', encoding="utf-8")
            self._git(root, "add", "--", "src/config.py")
            config.write_text("API_KEY = None\n", encoding="utf-8")
            project.transition("review")

            with self.assertRaisesRegex(AnchorError, "Pre-commit is blocked"):
                project.precommit()
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertTrue(
                any(
                    finding["category"] == "secret"
                    and "[index]" in finding["location"]
                    for finding in task["quality"][-1]["findings"]
                )
            )

    def test_unborn_git_head_secret_cannot_be_masked_by_baseline_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            config = root / "src" / "config.py"
            config.parent.mkdir(parents=True)
            config.write_text("API_KEY = None\n", encoding="utf-8")
            project = self._implementing_project(root, active_security=True)
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertTrue(task["change_baseline"]["git_unborn"])

            config.write_text('API_KEY = "abcdefgh-secret-value"\n', encoding="utf-8")
            self._git(root, "add", "--", "src/config.py")
            self._git(root, "commit", "--quiet", "-m", "malicious first commit")
            config.write_text("API_KEY = None\n", encoding="utf-8")
            project.transition("review")
            with self.assertRaisesRegex(AnchorError, "Pre-commit is blocked"):
                project.precommit()

    def test_git_initialized_after_non_git_approval_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "src" / "config.py"
            config.parent.mkdir(parents=True)
            config.write_text("API_KEY = None\n", encoding="utf-8")
            project = self._implementing_project(root, active_security=True)
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["change_baseline"]["git_context"], "none")

            self._init_git(root)
            config.write_text('API_KEY = "abcdefgh-secret-value"\n', encoding="utf-8")
            self._git(root, "add", "--", "src/config.py")
            self._git(root, "commit", "--quiet", "-m", "malicious first commit")
            config.write_text("API_KEY = None\n", encoding="utf-8")
            with self.assertRaisesRegex(AnchorError, "Git was initialized after"):
                project.transition("review")

    def test_staged_submodule_secret_before_approval_uses_head_gitlink_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            source.mkdir()
            self._init_git(source)
            self._commit_file(source, "src/config.py", "API_KEY = None\n")

            root = base / "project"
            root.mkdir()
            self._init_git(root)
            self._commit_file(root, "README.md")
            self._git(
                root,
                "-c",
                "protocol.file.allow=always",
                "clone",
                "--quiet",
                str(source),
                "vendor/library",
            )
            (root / ".gitmodules").write_text(
                "[submodule \"vendor/library\"]\n"
                "\tpath = vendor/library\n"
                f"\turl = {source.as_posix()}\n",
                encoding="utf-8",
            )
            source_head = self._git_output(source, "rev-parse", "HEAD")
            self._git(root, "add", "--", ".gitmodules")
            self._git(
                root,
                "update-index",
                "--add",
                "--cacheinfo",
                "160000",
                source_head,
                "vendor/library",
            )
            self._git(root, "commit", "--quiet", "-m", "add library")
            library = root / "vendor" / "library"
            self._git(library, "config", "user.name", "AnchorLoop Tests")
            self._git(
                library,
                "config",
                "user.email",
                "anchorloop-tests@example.invalid",
            )
            config = library / "src" / "config.py"
            config.write_text('API_KEY = "abcdefgh-secret-value"\n', encoding="utf-8")
            self._git(library, "add", "--", "src/config.py")
            self._git(library, "commit", "--quiet", "-m", "secret update")
            self._git(root, "add", "--", "vendor/library")
            config.write_text("API_KEY = None\n", encoding="utf-8")

            project = self._implementing_project(root, active_security=True)
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertNotEqual(
                task["change_baseline"]["submodule_oids"]["vendor/library"],
                self._git_output(library, "rev-parse", "HEAD"),
            )
            project.transition("review")
            with self.assertRaisesRegex(AnchorError, "Pre-commit is blocked"):
                project.precommit()

    def test_unborn_git_first_commit_recursively_scans_submodule_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            source.mkdir()
            self._init_git(source)
            self._commit_file(source, "auth/permissions.py", "ALLOW_ADMIN = True\n")

            root = base / "project"
            root.mkdir()
            self._init_git(root)
            self._git(
                root,
                "-c",
                "protocol.file.allow=always",
                "clone",
                "--quiet",
                str(source),
                "vendor/library",
            )
            library = root / "vendor" / "library"
            self._git(library, "config", "user.name", "AnchorLoop Tests")
            self._git(
                library,
                "config",
                "user.email",
                "anchorloop-tests@example.invalid",
            )
            project = self._implementing_project(root, active_security=True)
            permissions = library / "auth" / "permissions.py"
            permissions.write_text("ALLOW_ADMIN = False\n", encoding="utf-8")
            self._git(library, "add", "--", "auth/permissions.py")
            self._git(library, "commit", "--quiet", "-m", "permissions update")
            changed_head = self._git_output(library, "rev-parse", "HEAD")
            (root / ".gitmodules").write_text(
                "[submodule \"vendor/library\"]\n"
                "\tpath = vendor/library\n"
                f"\turl = {source.as_posix()}\n",
                encoding="utf-8",
            )
            self._git(root, "add", "--", ".gitmodules")
            self._git(
                root,
                "update-index",
                "--add",
                "--cacheinfo",
                "160000",
                changed_head,
                "vendor/library",
            )
            self._git(root, "commit", "--quiet", "-m", "first parent commit")
            permissions.write_text("ALLOW_ADMIN = True\n", encoding="utf-8")

            with self.assertRaisesRegex(
                AnchorError,
                r"vendor/library/auth/permissions\.py",
            ):
                project.transition("review")

    def test_quality_invalidates_masked_git_state_after_precommit(self) -> None:
        cases = ("staged-root", "committed-nested")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                repository = Path(directory)
                self._init_git(repository)
                root = repository if case == "staged-root" else repository / "nested"
                config_relative = (
                    "src/config.py"
                    if root == repository
                    else "nested/src/config.py"
                )
                config = self._commit_file(repository, config_relative, "API_KEY = None\n")
                project = self._implementing_project(root)
                project.transition("review")
                project.precommit()

                config.write_text('API_KEY = "abcdefgh-secret-value"\n', encoding="utf-8")
                self._git(repository, "add", "--", config_relative)
                config.write_text("API_KEY = None\n", encoding="utf-8")
                if case == "committed-nested":
                    self._git(repository, "commit", "--quiet", "-m", "masked secret")
                with self.assertRaisesRegex(AnchorError, "Code changed after the quality gate"):
                    project.verify_task(
                        by="Ada Engineer",
                        result="pass",
                        reason="The documented acceptance scenario passed.",
                        recall="Persisted retry state prevents duplicate acknowledgement.",
                    )

    def test_committed_whitespace_error_blocks_precommit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            self._commit_file(root, "src/retry.py", "ATTEMPTS = 3  \n")
            project.transition("review")

            with self.assertRaisesRegex(AnchorError, "Pre-commit is blocked"):
                project.precommit()
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertTrue(
                any(
                    finding["category"] == "whitespace"
                    for finding in task["quality"][-1]["findings"]
                )
            )

    def test_committed_sensitive_change_inside_submodule_blocks_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "secure-library"
            source.mkdir()
            self._init_git(source)
            self._commit_file(
                source,
                "auth/permissions.py",
                "ALLOW_ADMIN = True\n",
            )

            root = base / "project"
            root.mkdir()
            self._init_git(root)
            self._commit_file(root, "README.md")
            self._git(
                root,
                "-c",
                "protocol.file.allow=always",
                "clone",
                "--quiet",
                str(source),
                "vendor/secure-library",
            )
            source_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=source,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            (root / ".gitmodules").write_text(
                "[submodule \"vendor/secure-library\"]\n"
                "\tpath = vendor/secure-library\n"
                f"\turl = {source.as_posix()}\n",
                encoding="utf-8",
            )
            self._git(root, "add", "--", ".gitmodules")
            self._git(
                root,
                "update-index",
                "--add",
                "--cacheinfo",
                "160000",
                source_head,
                "vendor/secure-library",
            )
            self._git(root, "commit", "--quiet", "-m", "add secure library")
            project = self._implementing_project(root)

            nested = root / "vendor" / "secure-library"
            self._git(nested, "config", "user.name", "AnchorLoop Tests")
            self._git(
                nested,
                "config",
                "user.email",
                "anchorloop-tests@example.invalid",
            )
            permissions = nested / "auth" / "permissions.py"
            permissions.write_text("ALLOW_ADMIN = False\n", encoding="utf-8")
            self._git(nested, "add", "--", "auth/permissions.py")
            self._git(nested, "commit", "--quiet", "-m", "tighten permissions")

            with self.assertRaisesRegex(
                AnchorError,
                r"vendor/secure-library/auth/permissions\.py",
            ):
                project.transition("review")

    def test_uninitialized_submodule_can_rebaseline_after_plan_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "library"
            source.mkdir()
            self._init_git(source)
            self._commit_file(source, "src/library.py", "VALUE = 1\n")
            source_head = self._git_output(source, "rev-parse", "HEAD")

            root = base / "project"
            root.mkdir()
            self._init_git(root)
            self._commit_file(root, "README.md")
            (root / ".gitmodules").write_text(
                "[submodule \"vendor/library\"]\n"
                "\tpath = vendor/library\n"
                f"\turl = {source.as_posix()}\n",
                encoding="utf-8",
            )
            self._git(root, "add", "--", ".gitmodules")
            self._git(
                root,
                "update-index",
                "--add",
                "--cacheinfo",
                "160000",
                source_head,
                "vendor/library",
            )
            self._git(root, "commit", "--quiet", "-m", "add uninitialized library")
            project = self._implementing_project(root)
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertIsNone(task["change_baseline"]["submodules"]["vendor/library"])

            self._git(
                root,
                "-c",
                "protocol.file.allow=always",
                "clone",
                "--quiet",
                str(source),
                "vendor/library",
            )
            with self.assertRaisesRegex(AnchorError, "materialization changed"):
                project.transition("review")

            revised = project.revise_task(
                target="plan",
                reason="Materialize the approved submodule before implementation.",
            )
            self.assertIsNone(
                revised["change_baseline"]["submodules"]["vendor/library"]
            )
            self._plan(project, mode="STANDARD")
            approved = project.approve_task("Ada Engineer")
            self.assertEqual(
                approved["change_baseline"]["submodules"]["vendor/library"]["source"],
                "git",
            )
            project.transition("implement")
            self.assertEqual(project.transition("review")["state"], "review_ready")

    def test_filesystem_baseline_capture_fails_closed_on_read_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            risky = root / "auth" / "permissions.py"
            risky.parent.mkdir(parents=True)
            risky.write_text("ALLOW_ADMIN = True\n", encoding="utf-8")
            project = AnchorProject.at(root)
            project.apply_setup("add")
            project.start_task("Protect the actual implementation diff")
            project.record_brief(by="Ada Engineer", values=BRIEF)
            self._plan(project, mode="STANDARD")

            real_open = os.open
            risky_key = os.path.normcase(os.path.abspath(risky))

            def guarded_open(path: object, *args: object, **kwargs: object) -> int:
                candidate = os.path.normcase(os.path.abspath(os.fspath(path)))
                if candidate == risky_key:
                    raise PermissionError("simulated baseline read denial")
                return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

            with (
                mock.patch("anchorloop.quality.os.open", side_effect=guarded_open),
                self.assertRaisesRegex(
                    AnchorError,
                    "filesystem baseline inspection failed",
                ),
            ):
                project.approve_task("Ada Engineer")

            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "planned")

    def test_filesystem_baseline_capture_fails_closed_on_lstat_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            risky = root / "auth" / "permissions.py"
            risky.parent.mkdir(parents=True)
            risky.write_text("ALLOW_ADMIN = True\n", encoding="utf-8")
            project = AnchorProject.at(root)
            project.apply_setup("add")
            project.start_task("Protect the actual implementation diff")
            project.record_brief(by="Ada Engineer", values=BRIEF)
            self._plan(project, mode="STANDARD")

            real_lstat = os.lstat
            risky_key = os.path.normcase(os.path.abspath(risky))

            def guarded_lstat(path: object, *args: object, **kwargs: object) -> object:
                candidate = os.path.normcase(os.path.abspath(os.fspath(path)))
                if candidate == risky_key:
                    raise PermissionError("simulated baseline lstat denial")
                return real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]

            with (
                mock.patch("anchorloop.quality.os.lstat", side_effect=guarded_lstat),
                self.assertRaisesRegex(
                    AnchorError,
                    "filesystem baseline inspection failed",
                ),
            ):
                project.approve_task("Ada Engineer")

            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "planned")

    def test_filesystem_baseline_capture_fails_closed_on_scandir_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            risky_directory = root / "auth"
            risky_directory.mkdir()
            (risky_directory / "permissions.py").write_text(
                "ALLOW_ADMIN = True\n",
                encoding="utf-8",
            )
            project = AnchorProject.at(root)
            project.apply_setup("add")
            project.start_task("Protect the actual implementation diff")
            project.record_brief(by="Ada Engineer", values=BRIEF)
            self._plan(project, mode="STANDARD")

            real_scandir = os.scandir
            risky_key = os.path.normcase(os.path.abspath(risky_directory))

            def guarded_scandir(path: object) -> object:
                candidate = os.path.normcase(os.path.abspath(os.fspath(path)))
                if candidate == risky_key:
                    raise PermissionError("simulated baseline directory denial")
                return real_scandir(path)

            with (
                mock.patch(
                    "anchorloop.quality.os.scandir",
                    side_effect=guarded_scandir,
                ),
                self.assertRaisesRegex(
                    AnchorError,
                    "filesystem baseline inspection failed",
                ),
            ):
                project.approve_task("Ada Engineer")

            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "planned")

    def test_filesystem_baseline_entry_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.py").write_text("ONE = 1\n", encoding="utf-8")
            (root / "two.py").write_text("TWO = 2\n", encoding="utf-8")
            project = AnchorProject.at(root)
            project.apply_setup("add")
            project.start_task("Bound filesystem baseline entries")
            project.record_brief(by="Ada Engineer", values=BRIEF)
            self._plan(project, mode="STANDARD")

            with (
                mock.patch("anchorloop.quality._TASK_BASELINE_MAX_ENTRIES", 1),
                self.assertRaisesRegex(AnchorError, "entry limit exceeded"),
            ):
                project.approve_task("Ada Engineer")

    def test_filesystem_baseline_directory_only_entry_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(3):
                (root / f"empty-{index}").mkdir()
            project = AnchorProject.at(root)
            project.apply_setup("add")
            project.start_task("Bound filesystem baseline directory traversal")
            project.record_brief(by="Ada Engineer", values=BRIEF)
            self._plan(project, mode="STANDARD")

            with (
                mock.patch("anchorloop.quality._TASK_BASELINE_MAX_ENTRIES", 2),
                self.assertRaisesRegex(AnchorError, "entry limit exceeded"),
            ):
                project.approve_task("Ada Engineer")

    def test_filesystem_baseline_byte_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "payload.bin").write_bytes(b"12345")
            project = AnchorProject.at(root)
            project.apply_setup("add")
            project.start_task("Bound filesystem baseline bytes")
            project.record_brief(by="Ada Engineer", values=BRIEF)
            self._plan(project, mode="STANDARD")

            with (
                mock.patch("anchorloop.quality._TASK_BASELINE_MAX_BYTES", 4),
                self.assertRaisesRegex(AnchorError, "byte limit exceeded"),
            ):
                project.approve_task("Ada Engineer")

    @unittest.skipUnless(os.name == "nt", "Windows junctions are required")
    def test_filesystem_baseline_blocks_windows_junction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "permissions.py").write_text(
                "ALLOW_ADMIN = True\n",
                encoding="utf-8",
            )
            junction = root / "auth"
            created = subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(junction),
                    str(outside),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(f"junction creation unavailable: {created.stderr}")

            project = AnchorProject.at(root)
            project.apply_setup("add")
            project.start_task("Reject filesystem junctions")
            project.record_brief(by="Ada Engineer", values=BRIEF)
            self._plan(project, mode="STANDARD")

            with self.assertRaisesRegex(AnchorError, "reparse point"):
                project.approve_task("Ada Engineer")

    @unittest.skipUnless(os.name == "nt", "Windows junctions are required")
    def test_workspace_fingerprint_blocks_filesystem_junction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "secret.py").write_text("VALUE = 1\n", encoding="utf-8")
            junction = root / "linked"
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(f"junction creation unavailable: {created.stderr}")
            with self.assertRaisesRegex(GitInspectionError, "reparse point"):
                workspace_fingerprint(root)

    @unittest.skipUnless(os.name == "nt", "Windows junctions are required")
    def test_workspace_fingerprint_blocks_git_tracked_path_replaced_by_junction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            self._init_git(root)
            tracked = self._commit_file(root, "linked", "tracked file\n")
            tracked.unlink()
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(tracked), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(f"junction creation unavailable: {created.stderr}")
            with self.assertRaisesRegex(GitInspectionError, "reparse point"):
                workspace_fingerprint(root)

    def test_safe_committed_change_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            self._commit_file(root, "src/retry.py", "ATTEMPTS = 3\n")

            reviewed = project.transition("review")

            self.assertEqual(reviewed["state"], "review_ready")

    def test_approval_subject_and_digest_bind_change_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )

            subject = project._task_approval_subject(task)

            self.assertEqual(subject["change_baseline"], task["change_baseline"])
            self.assertEqual(task["change_baseline"]["source"], "git")
            self.assertEqual(
                task["approval"]["task_digest"],
                project._document_digest(subject),
            )

    def test_rewritten_approved_git_baseline_blocks_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            baseline_path = self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            baseline_path.write_text("rewritten history\n", encoding="utf-8")
            self._git(root, "add", "--", "README.md")
            self._git(root, "commit", "--quiet", "--amend", "--no-edit")

            with self.assertRaisesRegex(
                AnchorError,
                "approved Git baseline is no longer an ancestor",
            ):
                project.transition("review")
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "implementing")

    def test_rewritten_baseline_blocks_even_in_careful_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            baseline_path = self._commit_file(root, "README.md")
            project = self._implementing_project(root, mode="CAREFUL")
            baseline_path.write_text("rewritten history\n", encoding="utf-8")
            self._git(root, "add", "--", "README.md")
            self._git(root, "commit", "--quiet", "--amend", "--no-edit")

            with self.assertRaisesRegex(
                AnchorError,
                "approved Git baseline is no longer an ancestor",
            ):
                project.transition("review")

    def test_committed_rename_reports_both_old_and_new_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "auth/permissions.py")
            project = self._implementing_project(root)
            self._git(
                root,
                "mv",
                "--",
                "auth/permissions.py",
                "auth/access_control.py",
            )
            self._git(root, "commit", "--quiet", "-m", "rename auth module")

            with self.assertRaises(AnchorError) as raised:
                project.transition("review")

            message = str(raised.exception)
            self.assertIn("auth/permissions.py", message)
            self.assertIn("auth/access_control.py", message)

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
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)

            with (
                mock.patch("anchorloop.quality._git_bytes", return_value=None),
                self.assertRaisesRegex(AnchorError, "Cannot evaluate the actual diff safely"),
            ):
                project.transition("review")
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "implementing")

    def test_non_git_project_uses_filesystem_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._implementing_project(root)

            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                task["change_baseline"]["source"],
                "filesystem",
            )
            risky = root / "auth" / "permissions.py"
            risky.parent.mkdir(parents=True)
            risky.write_text("ALLOW_ADMIN = False\n", encoding="utf-8")

            with self.assertRaisesRegex(
                AnchorError,
                r"auth/permissions\.py",
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

    def test_historical_revision_does_not_preapprove_future_risk_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            auth = root / "auth" / "permissions.py"
            auth.parent.mkdir(parents=True)
            auth.write_text("ALLOW_ADMIN = False\n", encoding="utf-8")
            with self.assertRaisesRegex(AnchorError, r"auth/permissions\.py"):
                project.transition("review")

            revised = project.revise_task(
                target="plan",
                reason="Actual diff introduced CAREFUL risk paths.",
            )
            self.assertEqual(
                revised["revisions"][-1]["actual_diff_risk_paths"],
                ["auth/permissions.py"],
            )
            override = (
                "Engineer reviewed actual diff risk paths: auth/permissions.py "
                "and payments/new.py"
            )
            self._plan(project, mode="STANDARD", override=override)
            approved = project.approve_task("Ada Engineer")
            self.assertEqual(
                approved["approval"]["task_digest"],
                project._document_digest(project._task_approval_subject(approved)),
            )
            project.transition("implement")
            project.transition("review")

            payment = root / "payments" / "new.py"
            payment.parent.mkdir(parents=True)
            payment.write_text("ENABLED = False\n", encoding="utf-8")
            with self.assertRaisesRegex(AnchorError, r"payments/new\.py"):
                project.precommit()

    def test_actual_diff_revision_evidence_is_approval_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            risky = root / "auth" / "permissions.py"
            risky.parent.mkdir(parents=True)
            risky.write_text("ALLOW_ADMIN = False\n", encoding="utf-8")
            with self.assertRaises(AnchorError):
                project.transition("review")
            project.revise_task(
                target="plan",
                reason="Actual diff introduced CAREFUL risk paths.",
            )
            self._plan(
                project,
                mode="STANDARD",
                override="Engineer reviewed actual diff risk path: auth/permissions.py",
            )
            project.approve_task("Ada Engineer")
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            task["revisions"][-1]["actual_diff_risk_paths"].append("payments/new.py")
            project.active_task_path.write_text(json.dumps(task), encoding="utf-8")

            with self.assertRaisesRegex(AnchorError, "approved plan"):
                project.transition("implement")

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

    def test_precommit_rejects_git_metadata_change_during_snapshot_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            project.transition("review")
            starting = workspace_fingerprint(root)
            ending = {
                **starting,
                "git_state_digest": "sha256:" + "0" * 64,
            }
            with (
                mock.patch(
                    "anchorloop.quality.workspace_fingerprint",
                    side_effect=(starting, ending),
                ),
                self.assertRaisesRegex(AnchorError, "Pre-commit is blocked"),
            ):
                project.precommit()
            task = json.loads(project.active_task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["quality"][-1]["status"], "blocked")
            self.assertTrue(
                any(
                    finding["category"] == "workspace"
                    for finding in task["quality"][-1]["findings"]
                )
            )

    def test_plan_revision_preserves_original_diff_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            original = json.loads(project.active_task_path.read_text(encoding="utf-8"))[
                "change_baseline"
            ]["head"]
            self._commit_file(
                root,
                "auth/permissions.py",
                "ALLOW_ADMIN = False\n",
            )
            with self.assertRaisesRegex(AnchorError, r"auth/permissions\.py"):
                project.transition("review")

            revised = project.revise_task(
                target="plan",
                reason="Actual diff introduced CAREFUL risk paths.",
            )
            self.assertEqual(revised["change_baseline"]["head"], original)
            self._plan(project, mode="STANDARD")
            approved = project.approve_task("Ada Engineer")
            self.assertEqual(approved["change_baseline"]["head"], original)
            project.transition("implement")
            with self.assertRaisesRegex(AnchorError, r"auth/permissions\.py"):
                project.transition("review")

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

    def test_committed_migration_after_review_blocks_precommit_without_quality(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_git(root)
            self._commit_file(root, "README.md")
            project = self._implementing_project(root)
            reviewed = project.transition("review")
            self.assertEqual(reviewed["state"], "review_ready")
            self._commit_file(
                root,
                "migrations/0042.sql",
                "ALTER TABLE events ADD COLUMN attempts INTEGER;\n",
            )

            with self.assertRaisesRegex(
                AnchorError,
                r"migrations/0042\.sql",
            ):
                project.precommit()
            task = json.loads(
                project.active_task_path.read_text(encoding="utf-8")
            )
            self.assertEqual(task["state"], "review_ready")
            self.assertNotIn("quality", task)


if __name__ == "__main__":
    unittest.main()
