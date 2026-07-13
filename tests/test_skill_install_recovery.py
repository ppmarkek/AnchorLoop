from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
                "schema_version": 1,
                "destination": str(destination),
                "action": "install",
                "platform": "agents",
                "project_scoped": True,
                "version": "0.1.0",
                "runtime": "anchor",
                "writes": [installer._encoded_file("../../../../outside.txt", b"escape")],
                "deletes": [],
                "marker": installer._encoded_file(".anchorloop-skill.json", b"{}"),
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

            installation = installer.install(platform="agents", project_scoped=True)
            self.assertEqual(installation.destination, destination)
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
            updated_assets.append((Path("references/recovery.md"), b"Recovered bundle.\n"))

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

                installer.install(platform="codex", project_scoped=True)
                current = installer.installation_status(platform="codex", project_scoped=True)
                self.assertTrue(current["up_to_date"])

            self.assertIn(
                "Journal recovery update.",
                (destination / "SKILL.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (destination / "references" / "recovery.md").read_text(encoding="utf-8"),
                "Recovered bundle.\n",
            )
            marker = json.loads((destination / ".anchorloop-skill.json").read_text(encoding="utf-8"))
            self.assertIn("references/recovery.md", {entry["path"] for entry in marker["files"]})
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

            recovered = installer.uninstall(platform="agents", project_scoped=True)
            self.assertEqual(recovered.destination, destination)
            self.assertTrue(note.is_file())
            self.assertFalse((destination / "SKILL.md").exists())
            self.assertFalse((destination / ".anchorloop-skill.json").exists())
            self.assertFalse(
                installer.installation_status(platform="agents", project_scoped=True)["installed"]
            )
            _, journal_path = installer._journal_context(destination)
            self.assertFalse(journal_path.exists())


if __name__ == "__main__":
    unittest.main()
