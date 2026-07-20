from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anchorloop.cli import main
from anchorloop.safe_fs import AnchorError, SafeProjectFS
from anchorloop.skill_install import SKILL_RUNTIME_NPX, SkillInstaller


PLATFORM_PARTS = {
    "agents": ((".agents",), (".agents",)),
    "codex": ((".codex",), (".codex",)),
    "cursor": ((".cursor",), (".cursor",)),
    "gemini": ((".gemini",), (".gemini",)),
    "claude": ((".claude",), (".claude",)),
    "opencode": ((".opencode",), (".config", "opencode")),
}
PINNED_PACKAGE = "anchorloop@9.8.7"
FORBIDDEN_STATE = (
    ".anchor",
    "node_modules",
    "cache",
    ".cache",
    ".npm",
    ".npm-cache",
    "__pycache__",
)


class SkillInstallMatrixTests(unittest.TestCase):
    def test_project_and_global_platform_matrix(self) -> None:
        for platform, (project_parts, global_parts) in PLATFORM_PARTS.items():
            for project_scoped, location in ((True, project_parts), (False, global_parts)):
                with self.subTest(platform=platform, scope="project" if project_scoped else "global"):
                    self._exercise_installation(
                        platform=platform,
                        project_scoped=project_scoped,
                        location=location,
                    )

    def _exercise_installation(
        self,
        *,
        platform: str,
        project_scoped: bool,
        location: tuple[str, ...],
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "project"
            home = base / "home"
            project.mkdir()
            expected_root = project if project_scoped else home
            expected = expected_root.resolve().joinpath(*location, "skills", "anchorloop")

            with mock.patch("anchorloop.skill_install.Path.home", return_value=home):
                installer = SkillInstaller(project)
                preview = installer.preview_install(
                    platform=platform,
                    project_scoped=project_scoped,
                    runtime=SKILL_RUNTIME_NPX,
                    npx_package=PINNED_PACKAGE,
                )
                self.assertEqual(preview.destination, expected)
                self.assertIn(str(expected), "\n".join(preview.lines()))

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
                        raise RuntimeError("matrix install interruption")

                with mock.patch.object(SkillInstaller, "_write_bytes", side_effect=interrupted_write):
                    with self.assertRaisesRegex(RuntimeError, "matrix install interruption"):
                        installer.install(
                            platform=platform,
                            project_scoped=project_scoped,
                            runtime=SKILL_RUNTIME_NPX,
                            npx_package=PINNED_PACKAGE,
                        )

                with self.assertRaisesRegex(AnchorError, "Recovered interrupted skill install"):
                    installer.install(
                        platform=platform,
                        project_scoped=project_scoped,
                        runtime=SKILL_RUNTIME_NPX,
                        npx_package=PINNED_PACKAGE,
                    )
                installer.install(
                    platform=platform,
                    project_scoped=project_scoped,
                    runtime=SKILL_RUNTIME_NPX,
                    npx_package=PINNED_PACKAGE,
                )
                owned_files = {
                    path.relative_to(expected).as_posix()
                    for path in expected.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(
                    owned_files,
                    {"SKILL.md", "references/workflow.md", ".anchorloop-skill.json"},
                )

                marker_path = expected / ".anchorloop-skill.json"
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                self.assertEqual(marker["platform"], platform)
                self.assertEqual(marker["scope"], "project" if project_scoped else "user-global")
                self.assertEqual(marker["runtime"], "npx")
                self.assertEqual(marker["npx_package"], PINNED_PACKAGE)
                self.assertEqual(
                    {entry["path"] for entry in marker["files"]},
                    {"SKILL.md", "references/workflow.md"},
                )
                for entry in marker["files"]:
                    content = (expected / entry["path"]).read_bytes()
                    self.assertEqual(
                        entry["sha256"],
                        f"sha256:{hashlib.sha256(content).hexdigest()}",
                    )
                self.assertIn(
                    f"npx --yes {PINNED_PACKAGE} status",
                    (expected / "SKILL.md").read_text(encoding="utf-8"),
                )

                user_file = expected / "user-note.txt"
                user_file.write_text("preserve me\n", encoding="utf-8")
                installer.install(
                    platform=platform,
                    project_scoped=project_scoped,
                    runtime=SKILL_RUNTIME_NPX,
                    npx_package=PINNED_PACKAGE,
                )
                self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")

                skill = expected / "SKILL.md"
                skill.write_text(skill.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
                with self.assertRaisesRegex(AnchorError, "Refusing to update modified"):
                    installer.install(
                        platform=platform,
                        project_scoped=project_scoped,
                        runtime=SKILL_RUNTIME_NPX,
                        npx_package=PINNED_PACKAGE,
                    )
                self.assertIn("local edit", skill.read_text(encoding="utf-8"))

                installer.install(
                    platform=platform,
                    project_scoped=project_scoped,
                    runtime=SKILL_RUNTIME_NPX,
                    npx_package=PINNED_PACKAGE,
                    force=True,
                )
                installer.uninstall(platform=platform, project_scoped=project_scoped)
                self.assertTrue(user_file.is_file())
                self.assertFalse(marker_path.exists())
                self.assertFalse(skill.exists())
                self.assertFalse((expected / "references" / "workflow.md").exists())

            for root in (project, home):
                for relative_name in FORBIDDEN_STATE:
                    self.assertFalse((root / relative_name).exists(), f"{root / relative_name} leaked")

    def test_global_all_uses_only_native_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            home = Path(directory) / "home"
            root.mkdir()
            native_locations = (
                (".codex",),
                (".cursor",),
                (".gemini",),
                (".claude",),
                (".config", "opencode"),
            )
            with mock.patch("anchorloop.skill_install.Path.home", return_value=home):
                self.assertEqual(
                    main(["install", "--global", "--all", "--apply", "--path", str(root)]),
                    0,
                )
                for location in native_locations:
                    self.assertTrue(home.joinpath(*location, "skills", "anchorloop", "SKILL.md").is_file())
                self.assertFalse((home / ".agents" / "skills" / "anchorloop").exists())
                self.assertFalse((root / ".anchor").exists())

                self.assertEqual(
                    main(["uninstall", "--global", "--all", "--apply", "--path", str(root)]),
                    0,
                )
                for location in native_locations:
                    self.assertFalse(home.joinpath(*location, "skills", "anchorloop").exists())
                self.assertFalse((home / ".agents").exists())

    def test_marker_tampering_never_expands_uninstall_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="agents", project_scoped=True)
            installer.install(platform="agents", project_scoped=True)
            note = destination / "user-note.txt"
            note.write_text("preserve me\n", encoding="utf-8")
            marker_path = destination / ".anchorloop-skill.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["files"].append(
                {
                    "path": "user-note.txt",
                    "sha256": f"sha256:{hashlib.sha256(note.read_bytes()).hexdigest()}",
                }
            )
            marker_path.write_text(json.dumps(marker), encoding="utf-8")

            with self.assertRaisesRegex(AnchorError, "unknown owned paths"):
                installer.uninstall(platform="agents", project_scoped=True)
            self.assertTrue(note.is_file())
            self.assertTrue((destination / "SKILL.md").is_file())

            installer.uninstall(platform="agents", project_scoped=True, force=True)
            self.assertTrue(note.is_file())
            self.assertFalse(marker_path.exists())
            self.assertFalse((destination / "SKILL.md").exists())

    def test_force_update_repairs_injected_marker_without_deleting_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = SkillInstaller(root)
            destination = installer.destination_for(platform="codex", project_scoped=True)
            installer.install(platform="codex", project_scoped=True)
            note = destination / "user-note.txt"
            note.write_text("preserve me\n", encoding="utf-8")
            marker_path = destination / ".anchorloop-skill.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["files"].append(
                {
                    "path": "user-note.txt",
                    "sha256": f"sha256:{hashlib.sha256(note.read_bytes()).hexdigest()}",
                }
            )
            marker_path.write_text(json.dumps(marker), encoding="utf-8")

            installer.install(platform="codex", project_scoped=True, force=True)
            self.assertEqual(note.read_text(encoding="utf-8"), "preserve me\n")
            repaired = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {entry["path"] for entry in repaired["files"]},
                {"SKILL.md", "references/workflow.md"},
            )

    def test_force_does_not_accept_malformed_marker_entries(self) -> None:
        malformed_entries = (
            [
                {"path": "SKILL.md", "sha256": "sha256:" + "0" * 64},
                {"path": "SKILL.md", "sha256": "sha256:" + "0" * 64},
            ],
            [
                {"path": "SKILL.md", "sha256": "not-a-digest"},
                {"path": "references/workflow.md", "sha256": "sha256:" + "0" * 64},
            ],
            [
                {"path": "../outside.txt", "sha256": "sha256:" + "0" * 64},
                {"path": "SKILL.md", "sha256": "sha256:" + "0" * 64},
            ],
        )
        for entries in malformed_entries:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                installer = SkillInstaller(root)
                destination = installer.destination_for(platform="agents", project_scoped=True)
                installer.install(platform="agents", project_scoped=True)
                marker_path = destination / ".anchorloop-skill.json"
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                marker["files"] = entries
                marker_path.write_text(json.dumps(marker), encoding="utf-8")
                with self.assertRaises(AnchorError):
                    installer.install(platform="agents", project_scoped=True, force=True)


if __name__ == "__main__":
    unittest.main()
