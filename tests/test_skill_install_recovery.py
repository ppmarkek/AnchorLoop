from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from anchorloop.cli import main
from anchorloop.safe_fs import AnchorError, SafeProjectFS
from anchorloop.skill_install import SKILL_RUNTIME_ANCHOR, SkillInstaller


class SkillInstallRecoveryTests(unittest.TestCase):
    def test_pending_journal_paths_are_validated_before_recovery_mutates_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="agents", project_scoped=True)
            journal_filesystem, journal_path = installer._journal_context(destination)
            escaped = root / "outside.txt"
            journal = {
                "schema_version": 2,
                "destination": str(destination),
                "action": "install",
                "platform": "agents",
                "project_scoped": True,
                "version": "0.1.0",
                "runtime": "anchor",
                "writes": [
                    installer._encoded_file(
                        "../../../../outside.txt",
                        b"escape",
                        before={"kind": "missing"},
                    )
                ],
                "deletes": [],
                "marker": installer._encoded_file(
                    ".anchorloop-skill.json",
                    b"{}",
                    before={"kind": "missing"},
                ),
            }
            journal_filesystem.atomic_write_text(journal_path, json.dumps(journal) + "\n")
            try:
                status = installer.installation_status(platform="agents", project_scoped=True)
                self.assertTrue(status["recovery_pending"])
                self.assertEqual(status["recovery_action"], "unknown")
                self.assertIn("escape", status["recovery_error"])
                with self.assertRaises(AnchorError):
                    installer.install(platform="agents", project_scoped=True)
                self.assertFalse(escaped.exists())
                self.assertFalse(destination.exists())
            finally:
                journal_filesystem.unlink(journal_path, missing_ok=True)

    def test_interrupted_initial_install_is_reported_without_mutation_then_rolls_forward(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="agents", project_scoped=True)
            _, journal_path = installer._journal_context(destination)
            self.assertNotIn(root.resolve(), journal_path.resolve().parents)
            original_write = SkillInstaller._write_bytes
            writes = 0

            def interrupted_write(filesystem: SafeProjectFS, path: Path, content: bytes) -> None:
                nonlocal writes
                writes += 1
                self.assertTrue(journal_path.is_file(), "journal must be durable before the first asset write")
                original_write(filesystem, path, content)
                if writes == 1:
                    raise RuntimeError("simulated process interruption")

            with mock.patch.object(SkillInstaller, "_write_bytes", side_effect=interrupted_write):
                with self.assertRaisesRegex(RuntimeError, "simulated process interruption"):
                    installer.install(platform="agents", project_scoped=True)

            marker = destination / ".anchorloop-skill.json"
            self.assertTrue(journal_path.is_file())
            self.assertFalse(marker.exists())
            before = (destination / "SKILL.md").read_bytes()

            status = installer.installation_status(platform="agents", project_scoped=True)
            self.assertTrue(status["recovery_pending"])
            self.assertEqual(status["recovery_action"], "install")
            self.assertEqual((destination / "SKILL.md").read_bytes(), before)
            self.assertTrue(journal_path.is_file(), "status must not recover or delete the journal")

            with mock.patch.object(installer, "_commit_install_journal") as commit:
                with self.assertRaisesRegex(AnchorError, "Recovered interrupted skill install"):
                    installer.install(platform="agents", project_scoped=True)
            commit.assert_not_called()
            self.assertTrue(marker.is_file())
            self.assertFalse(journal_path.exists())
            final_status = installer.installation_status(platform="agents", project_scoped=True)
            self.assertFalse(final_status["recovery_pending"])
            self.assertTrue(final_status["up_to_date"])

    def test_interrupted_update_replays_the_journaled_bundle_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="codex", project_scoped=True)
            installer.install(platform="codex", project_scoped=True)

            baseline_assets = SkillInstaller._asset_files(
                runtime=SKILL_RUNTIME_ANCHOR,
                npx_package=None,
            )
            updated_assets: list[tuple[Path, bytes]] = []
            for path, content in baseline_assets:
                if path.as_posix() == "SKILL.md":
                    content += b"\nJournal recovery update.\n"
                updated_assets.append((path, content))

            original_write = SkillInstaller._write_bytes
            writes = 0

            def interrupted_write(filesystem: SafeProjectFS, path: Path, content: bytes) -> None:
                nonlocal writes
                writes += 1
                original_write(filesystem, path, content)
                if writes == 1:
                    raise RuntimeError("simulated update interruption")

            with mock.patch.object(SkillInstaller, "_asset_files", return_value=updated_assets):
                with mock.patch.object(SkillInstaller, "_write_bytes", side_effect=interrupted_write):
                    with self.assertRaisesRegex(RuntimeError, "simulated update interruption"):
                        installer.install(platform="codex", project_scoped=True)

                pending = installer.installation_status(platform="codex", project_scoped=True)
                self.assertTrue(pending["recovery_pending"])
                self.assertEqual(pending["recovery_action"], "install")

                with mock.patch.object(installer, "_commit_install_journal") as commit:
                    with self.assertRaisesRegex(AnchorError, "Recovered interrupted skill install"):
                        installer.install(platform="codex", project_scoped=True)
                commit.assert_not_called()
                current = installer.installation_status(platform="codex", project_scoped=True)
                self.assertTrue(current["up_to_date"])

            self.assertIn(
                "Journal recovery update.",
                (destination / "SKILL.md").read_text(encoding="utf-8"),
            )
            marker = json.loads((destination / ".anchorloop-skill.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {"SKILL.md", "references/workflow.md"},
                {entry["path"] for entry in marker["files"]},
            )
            _, journal_path = installer._journal_context(destination)
            self.assertFalse(journal_path.exists())

    def test_interrupted_uninstall_retries_to_success_and_preserves_unowned_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="agents", project_scoped=True)
            installer.install(platform="agents", project_scoped=True)
            note = destination / "user-note.txt"
            note.write_text("keep me\n", encoding="utf-8")

            original_unlink = SafeProjectFS.unlink
            owned_unlinks = 0

            def interrupted_unlink(
                filesystem: SafeProjectFS,
                path: Path,
                *,
                missing_ok: bool = False,
            ) -> None:
                nonlocal owned_unlinks
                candidate = Path(path)
                if destination in candidate.parents and candidate.name != ".anchorloop-skill.json":
                    owned_unlinks += 1
                    if owned_unlinks == 2:
                        raise RuntimeError("simulated uninstall interruption")
                original_unlink(filesystem, candidate, missing_ok=missing_ok)

            with mock.patch.object(SafeProjectFS, "unlink", new=interrupted_unlink):
                with self.assertRaisesRegex(RuntimeError, "simulated uninstall interruption"):
                    installer.uninstall(platform="agents", project_scoped=True)

            pending = installer.installation_status(platform="agents", project_scoped=True)
            self.assertTrue(pending["recovery_pending"])
            self.assertEqual(pending["recovery_action"], "uninstall")

            with self.assertRaisesRegex(AnchorError, "Recovered interrupted skill uninstall"):
                installer.uninstall(platform="agents", project_scoped=True)
            self.assertTrue(note.is_file())
            self.assertFalse((destination / "SKILL.md").exists())
            self.assertFalse((destination / ".anchorloop-skill.json").exists())
            self.assertFalse(
                installer.installation_status(platform="agents", project_scoped=True)["installed"]
            )
            _, journal_path = installer._journal_context(destination)
            self.assertFalse(journal_path.exists())

    def test_uninstall_recovery_requires_the_complete_owned_asset_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="agents", project_scoped=True)
            installer.install(platform="agents", project_scoped=True)
            filesystem = installer._filesystem_for(True)
            marker = json.loads(
                (destination / ".anchorloop-skill.json").read_text(encoding="utf-8")
            )
            journal = installer._uninstall_journal(
                filesystem=filesystem,
                destination=destination,
                platform="agents",
                project_scoped=True,
                version=marker["version"],
                runtime=marker["runtime"],
                owned_files=[],
            )
            journal_filesystem, journal_path = installer._journal_context(destination)
            journal_filesystem.atomic_write_text(journal_path, json.dumps(journal) + "\n")
            try:
                with self.assertRaisesRegex(AnchorError, "canonical asset bundle"):
                    installer.uninstall(platform="agents", project_scoped=True)
                self.assertTrue((destination / "SKILL.md").is_file())
                self.assertTrue((destination / "references" / "workflow.md").is_file())
                self.assertTrue((destination / ".anchorloop-skill.json").is_file())
            finally:
                journal_filesystem.unlink(journal_path, missing_ok=True)

    def test_recovery_stops_an_opposite_requested_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="agents", project_scoped=True)
            original_write = SkillInstaller._write_bytes
            writes = 0

            def interrupted_write(filesystem: SafeProjectFS, path: Path, content: bytes) -> None:
                nonlocal writes
                writes += 1
                original_write(filesystem, path, content)
                if writes == 1:
                    raise RuntimeError("simulated install interruption")

            with mock.patch.object(SkillInstaller, "_write_bytes", side_effect=interrupted_write):
                with self.assertRaisesRegex(RuntimeError, "simulated install interruption"):
                    installer.install(platform="agents", project_scoped=True)

            with self.assertRaisesRegex(AnchorError, "No new uninstall was started"):
                installer.uninstall(platform="agents", project_scoped=True)
            self.assertTrue((destination / ".anchorloop-skill.json").is_file())
            self.assertTrue((destination / "SKILL.md").is_file())
            _, journal_path = installer._journal_context(destination)
            self.assertFalse(journal_path.exists())

    def test_recovery_after_marker_write_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="agents", project_scoped=True)
            original_write = SkillInstaller._write_bytes

            def interrupt_after_marker(
                filesystem: SafeProjectFS,
                path: Path,
                content: bytes,
            ) -> None:
                original_write(filesystem, path, content)
                if path.name == ".anchorloop-skill.json":
                    raise RuntimeError("simulated marker interruption")

            with mock.patch.object(SkillInstaller, "_write_bytes", side_effect=interrupt_after_marker):
                with self.assertRaisesRegex(RuntimeError, "simulated marker interruption"):
                    installer.install(platform="agents", project_scoped=True)

            marker = destination / ".anchorloop-skill.json"
            self.assertTrue(marker.is_file())
            with mock.patch.object(SkillInstaller, "_write_bytes") as write:
                with self.assertRaisesRegex(AnchorError, "Recovered interrupted skill install"):
                    installer.install(platform="agents", project_scoped=True)
            write.assert_not_called()
            _, journal_path = installer._journal_context(destination)
            self.assertFalse(journal_path.exists())

    def test_recovery_refuses_to_overwrite_a_post_crash_user_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="agents", project_scoped=True)
            installer.install(platform="agents", project_scoped=True)

            updated_assets = []
            for path, content in SkillInstaller._asset_files(
                runtime=SKILL_RUNTIME_ANCHOR,
                npx_package=None,
            ):
                if path.as_posix() == "SKILL.md":
                    content += b"\nInterrupted update bundle.\n"
                updated_assets.append((path, content))

            original_write = SkillInstaller._write_bytes
            writes = 0

            def interrupted_write(filesystem: SafeProjectFS, path: Path, content: bytes) -> None:
                nonlocal writes
                writes += 1
                original_write(filesystem, path, content)
                if writes == 1:
                    raise RuntimeError("simulated update interruption")

            with mock.patch.object(SkillInstaller, "_asset_files", return_value=updated_assets):
                with mock.patch.object(SkillInstaller, "_write_bytes", side_effect=interrupted_write):
                    with self.assertRaisesRegex(RuntimeError, "simulated update interruption"):
                        installer.install(platform="agents", project_scoped=True)

                skill = destination / "SKILL.md"
                skill.write_text("post-crash user edit\n", encoding="utf-8")
                journal_filesystem, journal_path = installer._journal_context(destination)
                try:
                    with self.assertRaisesRegex(AnchorError, "changed after the operation was journaled"):
                        installer.install(platform="agents", project_scoped=True)
                    self.assertEqual(skill.read_text(encoding="utf-8"), "post-crash user edit\n")
                    self.assertTrue(journal_path.is_file())
                finally:
                    journal_filesystem.unlink(journal_path, missing_ok=True)

    def test_recovery_refuses_to_delete_a_post_crash_recreated_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="agents", project_scoped=True)
            installer.install(platform="agents", project_scoped=True)

            original_unlink = SafeProjectFS.unlink
            removed: Path | None = None
            removed_content: bytes | None = None

            def interrupted_unlink(
                filesystem: SafeProjectFS,
                path: Path,
                *,
                missing_ok: bool = False,
            ) -> None:
                nonlocal removed, removed_content
                candidate = Path(path)
                if removed is None and destination in candidate.parents and candidate.name != ".anchorloop-skill.json":
                    removed_content = filesystem.read_bytes(candidate)
                    original_unlink(filesystem, candidate, missing_ok=missing_ok)
                    removed = candidate
                    raise RuntimeError("simulated uninstall interruption")
                original_unlink(filesystem, candidate, missing_ok=missing_ok)

            with mock.patch.object(SafeProjectFS, "unlink", new=interrupted_unlink):
                with self.assertRaisesRegex(RuntimeError, "simulated uninstall interruption"):
                    installer.uninstall(platform="agents", project_scoped=True)

            self.assertIsNotNone(removed)
            self.assertIsNotNone(removed_content)
            assert removed is not None
            assert removed_content is not None
            removed.parent.mkdir(parents=True, exist_ok=True)
            removed.write_bytes(removed_content)
            journal_filesystem, journal_path = installer._journal_context(destination)
            try:
                with self.assertRaisesRegex(AnchorError, "changed after the operation was journaled"):
                    installer.uninstall(platform="agents", project_scoped=True)
                self.assertEqual(removed.read_bytes(), removed_content)
                self.assertTrue(journal_path.is_file())
            finally:
                journal_filesystem.unlink(journal_path, missing_ok=True)

    def test_global_all_install_recovers_before_any_fresh_destination_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            installer = SkillInstaller(root)
            original_write = SkillInstaller._write_bytes
            writes = 0

            def interrupted_write(
                filesystem: SafeProjectFS,
                path: Path,
                content: bytes,
            ) -> None:
                nonlocal writes
                writes += 1
                original_write(filesystem, path, content)
                if writes == 1:
                    raise RuntimeError("simulated global install interruption")

            with mock.patch("anchorloop.skill_install.Path.home", return_value=home):
                with mock.patch.object(
                    SkillInstaller,
                    "_write_bytes",
                    side_effect=interrupted_write,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "simulated global install interruption",
                    ):
                        installer.install(
                            platform="gemini",
                            project_scoped=False,
                        )

                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result = main(
                        [
                            "install",
                            "--global",
                            "--all",
                            "--apply",
                            "--path",
                            str(root),
                        ]
                    )
                self.assertEqual(result, 2)
                gemini = installer.destination_for(
                    platform="gemini",
                    project_scoped=False,
                )
                self.assertTrue((gemini / ".anchorloop-skill.json").is_file())
                for platform in ("codex", "cursor", "claude", "opencode"):
                    destination = installer.destination_for(
                        platform=platform,
                        project_scoped=False,
                    )
                    self.assertFalse(destination.exists(), platform)

    def test_global_all_uninstall_recovers_before_any_fresh_destination_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            installer = SkillInstaller(root)
            platforms = ("codex", "cursor", "gemini", "claude", "opencode")

            with mock.patch("anchorloop.skill_install.Path.home", return_value=home):
                for platform in platforms:
                    installer.install(platform=platform, project_scoped=False)

                gemini = installer.destination_for(
                    platform="gemini",
                    project_scoped=False,
                )
                original_unlink = SafeProjectFS.unlink
                removed = False

                def interrupted_unlink(
                    filesystem: SafeProjectFS,
                    path: Path,
                    *,
                    missing_ok: bool = False,
                ) -> None:
                    nonlocal removed
                    candidate = Path(path)
                    if (
                        not removed
                        and gemini in candidate.parents
                        and candidate.name != ".anchorloop-skill.json"
                    ):
                        original_unlink(
                            filesystem,
                            candidate,
                            missing_ok=missing_ok,
                        )
                        removed = True
                        raise RuntimeError("simulated global uninstall interruption")
                    original_unlink(filesystem, candidate, missing_ok=missing_ok)

                with mock.patch.object(
                    SafeProjectFS,
                    "unlink",
                    new=interrupted_unlink,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "simulated global uninstall interruption",
                    ):
                        installer.uninstall(
                            platform="gemini",
                            project_scoped=False,
                        )

                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result = main(
                        [
                            "uninstall",
                            "--global",
                            "--all",
                            "--apply",
                            "--path",
                            str(root),
                        ]
                    )
                self.assertEqual(result, 2)
                self.assertFalse((gemini / ".anchorloop-skill.json").exists())
                self.assertFalse((gemini / "SKILL.md").exists())
                for platform in ("codex", "cursor", "claude", "opencode"):
                    destination = installer.destination_for(
                        platform=platform,
                        project_scoped=False,
                    )
                    self.assertTrue(
                        (destination / ".anchorloop-skill.json").is_file(),
                        platform,
                    )


if __name__ == "__main__":
    unittest.main()
