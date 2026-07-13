from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path
from typing import Any

from .project import AnchorError


SKILL_NAME = "anchorloop"
SUPPORTED_PLATFORMS = ("agents", "codex")
_MARKER_NAME = ".anchorloop-skill.json"


@dataclass(frozen=True)
class SkillInstallPreview:
    destination: Path
    platform: str
    project_scoped: bool
    action: str

    def lines(self) -> list[str]:
        scope = "project" if self.project_scoped else "user-global"
        verb = "install or update" if self.action == "install" else "remove"
        return [
            f"AnchorLoop skill {self.action} preview ({scope}, {self.platform})",
            f"Will {verb} only AnchorLoop-owned skill assets at: {self.destination}",
            "Will not modify .anchor/ workflow state, application source, AGENTS.md, hooks, or Graphify settings.",
            "The installed skill is a thin adapter: the anchor CLI and .anchor/ state remain the source of truth.",
        ]


@dataclass(frozen=True)
class SkillInstallation:
    destination: Path
    platform: str
    project_scoped: bool
    version: str


class SkillInstaller:
    """Install the packaged thin agent adapter without owning workflow state."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def preview_install(self, *, platform: str, project_scoped: bool) -> SkillInstallPreview:
        return SkillInstallPreview(
            destination=self.destination_for(platform=platform, project_scoped=project_scoped),
            platform=platform,
            project_scoped=project_scoped,
            action="install",
        )

    def preview_uninstall(self, *, platform: str, project_scoped: bool) -> SkillInstallPreview:
        return SkillInstallPreview(
            destination=self.destination_for(platform=platform, project_scoped=project_scoped),
            platform=platform,
            project_scoped=project_scoped,
            action="uninstall",
        )

    def destination_for(self, *, platform: str, project_scoped: bool) -> Path:
        self._validate_platform(platform)
        if project_scoped:
            base = self.root
        else:
            base = Path.home()
        platform_dir = ".agents" if platform == "agents" else ".codex"
        return base / platform_dir / "skills" / SKILL_NAME

    def install(
        self,
        *,
        platform: str,
        project_scoped: bool,
        force: bool = False,
    ) -> SkillInstallation:
        destination = self.destination_for(platform=platform, project_scoped=project_scoped)
        marker_path = destination / _MARKER_NAME
        if destination.exists() and not marker_path.exists() and not force:
            raise AnchorError(
                f"Refusing to overwrite {destination}: it is not marked as an AnchorLoop skill install. "
                "Inspect it or rerun with --force."
            )

        previous_files: dict[str, str | None] = {}
        if marker_path.exists():
            previous_marker = self._read_marker(marker_path)
            if previous_marker.get("platform") != platform:
                raise AnchorError(f"Skill marker at {destination} is for a different platform.")
            previous_files = self._marker_files(previous_marker, marker_path)
            self._require_unmodified_assets(
                destination,
                previous_files,
                force=force,
                operation="update",
            )

        asset_files = self._asset_files()
        new_file_digests = {
            path.as_posix(): self._digest(content)
            for path, content in asset_files
        }
        for relative_path, content in asset_files:
            target = self._safe_child(destination, relative_path)
            self._write_bytes(target, content)

        for relative_name in previous_files:
            if relative_name in new_file_digests:
                continue
            target = self._safe_child(destination, Path(relative_name))
            if target.exists() and target.is_file():
                target.unlink()
            self._remove_empty_parents(target.parent, destination)

        installed_version = self._installed_version()
        marker = {
            "schema_version": 1,
            "skill": SKILL_NAME,
            "platform": platform,
            "scope": "project" if project_scoped else "user-global",
            "version": installed_version,
            "files": [
                {"path": path.as_posix(), "sha256": new_file_digests[path.as_posix()]}
                for path, _ in asset_files
            ],
        }
        self._write_text(marker_path, json.dumps(marker, indent=2, sort_keys=True) + "\n")
        return SkillInstallation(
            destination=destination,
            platform=platform,
            project_scoped=project_scoped,
            version=installed_version,
        )

    def uninstall(
        self,
        *,
        platform: str,
        project_scoped: bool,
        force: bool = False,
    ) -> SkillInstallation:
        destination = self.destination_for(platform=platform, project_scoped=project_scoped)
        marker_path = destination / _MARKER_NAME
        if not marker_path.exists():
            raise AnchorError(f"No AnchorLoop skill installation is recorded at {destination}.")

        marker = self._read_marker(marker_path)
        recorded_platform = marker.get("platform")
        if recorded_platform != platform:
            raise AnchorError(f"Skill marker at {destination} is for platform '{recorded_platform}', not '{platform}'.")

        paths = self._marker_files(marker, marker_path)
        self._require_unmodified_assets(destination, paths, force=force, operation="uninstall")
        for relative_name in sorted(paths, key=lambda value: value.count("/"), reverse=True):
            target = self._safe_child(destination, Path(relative_name))
            if target.exists() and target.is_file():
                target.unlink()
            self._remove_empty_parents(target.parent, destination)

        marker_path.unlink()
        self._remove_empty_parents(destination, destination.parent)
        return SkillInstallation(
            destination=destination,
            platform=platform,
            project_scoped=project_scoped,
            version=str(marker.get("version", "unknown")),
        )

    def installation_status(self, *, platform: str, project_scoped: bool) -> dict[str, Any]:
        destination = self.destination_for(platform=platform, project_scoped=project_scoped)
        marker_path = destination / _MARKER_NAME
        if not marker_path.exists():
            return {"installed": False, "destination": str(destination)}
        marker = self._read_marker(marker_path)
        return {
            "installed": True,
            "destination": str(destination),
            "platform": marker.get("platform"),
            "version": marker.get("version"),
            "current_version": self._installed_version(),
            "up_to_date": marker.get("version") == self._installed_version(),
        }

    @staticmethod
    def _validate_platform(platform: str) -> None:
        if platform not in SUPPORTED_PLATFORMS:
            supported = ", ".join(SUPPORTED_PLATFORMS)
            raise AnchorError(f"Skill platform must be one of: {supported}.")

    @staticmethod
    def _installed_version() -> str:
        try:
            return version("anchorloop")
        except PackageNotFoundError:
            return "0.1.0"

    @staticmethod
    def _asset_files() -> list[tuple[Path, bytes]]:
        root = files("anchorloop").joinpath("skills", SKILL_NAME)
        if not root.is_dir():
            raise AnchorError("AnchorLoop skill assets are missing from this installation.")

        assets: list[tuple[Path, bytes]] = []

        def collect(directory: Any, relative_root: Path) -> None:
            for child in sorted(directory.iterdir(), key=lambda item: item.name):
                relative_path = relative_root / child.name
                if child.is_dir():
                    collect(child, relative_path)
                else:
                    assets.append((relative_path, child.read_bytes()))

        collect(root, Path())
        return assets

    @staticmethod
    def _safe_child(root: Path, relative_path: Path) -> Path:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise AnchorError("Skill asset path escapes its installation directory.")
        resolved_root = root.resolve()
        candidate = (resolved_root / relative_path).resolve()
        if resolved_root != candidate.parent and resolved_root not in candidate.parents:
            raise AnchorError("Skill asset path escapes its installation directory.")
        return candidate

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        SkillInstaller._write_bytes(path, content.encode("utf-8"))

    @staticmethod
    def _write_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.anchorloop.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _read_marker(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AnchorError(f"Cannot read AnchorLoop skill marker at {path}.") from error
        if not isinstance(data, dict) or data.get("skill") != SKILL_NAME:
            raise AnchorError(f"AnchorLoop skill marker at {path} is invalid.")
        return data

    @staticmethod
    def _marker_files(marker: dict[str, Any], marker_path: Path) -> dict[str, str | None]:
        paths = marker.get("files")
        if not isinstance(paths, list):
            raise AnchorError(f"AnchorLoop skill marker at {marker_path} is invalid.")

        result: dict[str, str | None] = {}
        for entry in paths:
            if isinstance(entry, str):
                result[entry] = None
                continue
            if not isinstance(entry, dict):
                raise AnchorError(f"AnchorLoop skill marker at {marker_path} is invalid.")
            path = entry.get("path")
            digest = entry.get("sha256")
            if not isinstance(path, str) or not isinstance(digest, str):
                raise AnchorError(f"AnchorLoop skill marker at {marker_path} is invalid.")
            result[path] = digest
        return result

    def _require_unmodified_assets(
        self,
        destination: Path,
        paths: dict[str, str | None],
        *,
        force: bool,
        operation: str,
    ) -> None:
        if force:
            return
        modified: list[str] = []
        for relative_name, expected_digest in paths.items():
            target = self._safe_child(destination, Path(relative_name))
            if not target.exists():
                continue
            if not target.is_file() or expected_digest is None:
                modified.append(relative_name)
                continue
            try:
                actual_digest = self._digest(target.read_bytes())
            except OSError:
                modified.append(relative_name)
                continue
            if actual_digest != expected_digest:
                modified.append(relative_name)
        if modified:
            names = ", ".join(sorted(modified))
            raise AnchorError(
                f"Refusing to {operation} modified or legacy-managed skill assets: {names}. "
                "Inspect them or rerun with --force."
            )

    @staticmethod
    def _digest(content: bytes) -> str:
        return f"sha256:{hashlib.sha256(content).hexdigest()}"

    @staticmethod
    def _remove_empty_parents(path: Path, stop_before: Path) -> None:
        current = path
        while current != stop_before:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent
