from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anchorloop.cli import main
from anchorloop.project import AnchorError
from anchorloop.quality import workspace_fingerprint
from anchorloop.safe_fs import SafeProjectFS
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

    def test_new_file_mode_policy_distinguishes_state_and_portable_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filesystem = SafeProjectFS(root)
            state_mode = 0o666 if os.name == "nt" else 0o600
            portable_mode = 0o666 if os.name == "nt" else 0o644

            self.assertEqual(filesystem.mode_for_write(root / ".anchor" / "config.json"), state_mode)
            self.assertEqual(filesystem.mode_for_write(root / ".gitignore"), portable_mode)
            self.assertEqual(
                filesystem.mode_for_write(root / ".agents" / "skills" / "anchorloop" / "SKILL.md"),
                portable_mode,
            )

    @unittest.skipUnless(os.name == "posix", "POSIX permission semantics are required")
    def test_atomic_write_preserves_existing_repository_file_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filesystem = SafeProjectFS(root)
            for filename in (".gitignore", ".graphifyignore"):
                with self.subTest(filename=filename):
                    target = root / filename
                    target.write_text("old\n", encoding="utf-8")
                    os.chmod(target, 0o640)

                    filesystem.atomic_write_text(target, "new\n")

                    self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
                    self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o640)

    @unittest.skipUnless(os.name == "posix", "POSIX permission semantics are required")
    def test_setup_preserves_existing_gitignore_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gitignore = root / ".gitignore"
            gitignore.write_text("coverage/\n", encoding="utf-8")
            os.chmod(gitignore, 0o640)

            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)

            self.assertIn(".anchor/cache/", gitignore.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(os.stat(gitignore).st_mode), 0o640)

    @unittest.skipUnless(os.name == "posix", "POSIX permission semantics are required")
    def test_new_anchor_state_and_portable_assets_use_safe_default_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            self.assertEqual(main(["add", "--path", str(root), "--apply"]), 0)
            self.assertEqual(stat.S_IMODE(os.stat(root / ".anchor" / "config.json").st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(root / ".gitignore").st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(os.stat(root / ".graphifyignore").st_mode), 0o644)

            self.assertEqual(
                main(
                    [
                        "install",
                        "--project",
                        "--platform",
                        "agents",
                        "--apply",
                        "--path",
                        str(root),
                    ]
                ),
                0,
            )
            skill = root / ".agents" / "skills" / "anchorloop" / "SKILL.md"
            self.assertEqual(stat.S_IMODE(os.stat(skill).st_mode), 0o644)

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
            for platform, managed_directory in (
                ("agents", ".agents"),
                ("codex", ".codex"),
                ("cursor", ".cursor"),
                ("gemini", ".gemini"),
                ("claude", ".claude"),
                ("opencode", ".opencode"),
            ):
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

    def test_global_skill_install_rejects_symlinked_managed_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for platform, managed_parts in (
                ("agents", (".agents",)),
                ("codex", (".codex",)),
                ("cursor", (".cursor",)),
                ("gemini", (".gemini",)),
                ("claude", (".claude",)),
                ("opencode", (".config", "opencode")),
            ):
                project = base / f"project-global-{platform}"
                home = base / f"home-{platform}"
                outside = base / f"outside-global-{platform}"
                project.mkdir()
                home.mkdir()
                outside.mkdir()
                managed = home.joinpath(*managed_parts)
                managed.parent.mkdir(parents=True, exist_ok=True)
                self._symlink_or_skip(outside, managed, directory=True)

                with mock.patch("anchorloop.skill_install.Path.home", return_value=home):
                    self.assertEqual(
                        main(
                            [
                                "install",
                                "--global",
                                "--platform",
                                platform,
                                "--apply",
                                "--force",
                                "--path",
                                str(project),
                            ]
                        ),
                        2,
                    )
                self.assertFalse((outside / "skills" / "anchorloop").exists())

    def test_windows_reparse_attribute_is_rejected_deterministically(self) -> None:
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        metadata = mock.Mock(
            st_mode=stat.S_IFDIR | 0o755,
            st_file_attributes=reparse_flag,
        )
        with (
            mock.patch.object(
                stat,
                "FILE_ATTRIBUTE_REPARSE_POINT",
                reparse_flag,
                create=True,
            ),
            self.assertRaisesRegex(AnchorError, "symlink or reparse-point"),
        ):
            SafeProjectFS._reject_link(Path("managed"), metadata)

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
