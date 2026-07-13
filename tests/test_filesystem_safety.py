from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from anchorloop.cli import main
from anchorloop.project import AnchorError
from anchorloop.quality import workspace_fingerprint
from anchorloop.skill_install import SkillInstaller


class FilesystemSafetyTests(unittest.TestCase):
    def _symlink_or_skip(self, target: Path, link: Path, *, directory: bool = False) -> None:
        try:
            os.symlink(target, link, target_is_directory=directory)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symlink creation is unavailable in this test environment: {error}")

    def test_atomic_write_does_not_follow_precreated_temp_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            sentinel = base / "outside.txt"
            sentinel.write_text("outside remains unchanged\n", encoding="utf-8")

            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            legacy_temp = root / ".anchor" / ".next-action.md.tmp"
            self._symlink_or_skip(sentinel, legacy_temp)

            self.assertEqual(main(["start", "Safe temp write", "--path", str(root)]), 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside remains unchanged\n")

    def test_setup_rejects_symlinked_anchor_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            sentinel = outside / "config.json"
            sentinel.write_text("outside remains unchanged\n", encoding="utf-8")
            self._symlink_or_skip(outside, root / ".anchor", directory=True)

            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 2)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside remains unchanged\n")

    def test_event_log_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            sentinel = base / "outside-events.jsonl"
            sentinel.write_text("outside remains unchanged\n", encoding="utf-8")
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            events = root / ".anchor" / "events.jsonl"
            events.unlink()
            self._symlink_or_skip(sentinel, events)

            self.assertEqual(main(["start", "Reject unsafe event log", "--path", str(root)]), 2)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside remains unchanged\n")

    def test_graphifyignore_and_state_reads_reject_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            sentinel = base / "outside.txt"
            sentinel.write_text("outside remains unchanged\n", encoding="utf-8")
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)

            graphify_ignore = root / ".graphifyignore"
            graphify_ignore.unlink()
            self._symlink_or_skip(sentinel, graphify_ignore)
            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 2)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside remains unchanged\n")

            graphify_ignore.unlink()
            graphify_ignore.write_text(".anchor/\n", encoding="utf-8")
            config = root / ".anchor" / "config.json"
            config.unlink()
            self._symlink_or_skip(sentinel, config)
            self.assertEqual(main(["status", "--path", str(root)]), 2)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside remains unchanged\n")

    def test_project_skill_install_rejects_symlinked_managed_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for platform, managed_directory in (("agents", ".agents"), ("codex", ".codex")):
                root = base / f"project-{platform}"
                outside = base / f"outside-{platform}"
                root.mkdir()
                outside.mkdir()
                self._symlink_or_skip(outside, root / managed_directory, directory=True)

                self.assertEqual(
                    main(
                        [
                            "install",
                            "--project",
                            "--platform",
                            platform,
                            "--apply",
                            "--force",
                            "--path",
                            str(root),
                        ]
                    ),
                    2,
                )
                self.assertFalse((outside / "skills" / "anchorloop").exists())

    def test_installer_temp_and_marker_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            sentinel = base / "outside.txt"
            sentinel.write_text("outside remains unchanged\n", encoding="utf-8")
            install = ["install", "--project", "--platform", "agents", "--apply", "--path", str(root)]
            self.assertEqual(main(install), 0)

            destination = root / ".agents" / "skills" / "anchorloop"
            legacy_temp = destination / ".SKILL.md.anchorloop.tmp"
            self._symlink_or_skip(sentinel, legacy_temp)
            self.assertEqual(main([*install, "--force"]), 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside remains unchanged\n")

            marker = destination / ".anchorloop-skill.json"
            marker.unlink()
            self._symlink_or_skip(sentinel, marker)
            with self.assertRaises(AnchorError):
                SkillInstaller(root).installation_status(platform="agents", project_scoped=True)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside remains unchanged\n")

    def test_workspace_fingerprint_has_unambiguous_file_framing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a").write_bytes(b"hello")
            (root / "b").write_bytes(b"world")
            first = workspace_fingerprint(root)

            (root / "b").unlink()
            (root / "a").write_bytes(b"hello\0file\0path\01\0b\0world")
            second = workspace_fingerprint(root)

            self.assertEqual(first["format_version"], 3)
            self.assertNotEqual(first["digest"], second["digest"])
