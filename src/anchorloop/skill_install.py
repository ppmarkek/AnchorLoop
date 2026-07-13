from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path
from typing import Any

from .safe_fs import AnchorError, SafeProjectFS


SKILL_NAME = "anchorloop"
SUPPORTED_PLATFORMS = ("agents", "codex")
SKILL_RUNTIME_ANCHOR = "anchor"
SKILL_RUNTIME_NPX = "npx"
SUPPORTED_SKILL_RUNTIMES = (SKILL_RUNTIME_ANCHOR, SKILL_RUNTIME_NPX)
_MARKER_NAME = ".anchorloop-skill.json"
_NPX_PACKAGE_PATTERN = re.compile(
    r"(?:[a-z0-9][a-z0-9._-]*|@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*)"
    r"@[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
)


@dataclass(frozen=True)
class SkillInstallPreview:
    destination: Path
    platform: str
    project_scoped: bool
    action: str
    runtime: str = SKILL_RUNTIME_ANCHOR
    npx_package: str | None = None

    def lines(self) -> list[str]:
        scope = "project" if self.project_scoped else "user-global"
        verb = "install or update" if self.action == "install" else "remove"
        lines = [
            f"AnchorLoop skill {self.action} preview ({scope}, {self.platform})",
            f"Will {verb} only AnchorLoop-owned skill assets at: {self.destination}",
            "Will not modify .anchor/ workflow state, application source, AGENTS.md, hooks, or Graphify settings.",
            "The installed skill is a thin adapter: the anchor CLI and .anchor/ state remain the source of truth.",
        ]
        if self.action == "install" and self.runtime == SKILL_RUNTIME_NPX:
            lines.append(
                f"The installed skill will run the packaged CLI through: npx --yes {self.npx_package}"
            )
        return lines


@dataclass(frozen=True)
class SkillInstallation:
    destination: Path
    platform: str
    project_scoped: bool
    version: str
    runtime: str


class SkillInstaller:
    """Install the packaged thin agent adapter without owning workflow state."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._project_fs = SafeProjectFS(self.root)

    def preview_install(
        self,
        *,
        platform: str,
        project_scoped: bool,
        runtime: str = SKILL_RUNTIME_ANCHOR,
        npx_package: str | None = None,
    ) -> SkillInstallPreview:
        self._validate_runtime(runtime, npx_package)
        return SkillInstallPreview(
            destination=self.destination_for(platform=platform, project_scoped=project_scoped),
            platform=platform,
            project_scoped=project_scoped,
            action="install",
            runtime=runtime,
            npx_package=npx_package,
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
        filesystem = self._filesystem_for(project_scoped)
        platform_dir = ".agents" if platform == "agents" else ".codex"
        return filesystem.path(platform_dir, "skills", SKILL_NAME)

    def _filesystem_for(self, project_scoped: bool) -> SafeProjectFS:
        if project_scoped:
            return self._project_fs
        return SafeProjectFS(Path.home())

    def install(
        self,
        *,
        platform: str,
        project_scoped: bool,
        runtime: str = SKILL_RUNTIME_ANCHOR,
        npx_package: str | None = None,
        force: bool = False,
    ) -> SkillInstallation:
        self._validate_runtime(runtime, npx_package)
        filesystem = self._filesystem_for(project_scoped)
        destination = self.destination_for(platform=platform, project_scoped=project_scoped)
        marker_path = self._safe_child(filesystem, destination, Path(_MARKER_NAME))
        if filesystem.exists(destination) and not filesystem.exists(marker_path) and not force:
            raise AnchorError(
                f"Refusing to overwrite {destination}: it is not marked as an AnchorLoop skill install. "
                "Inspect it or rerun with --force."
            )

        previous_files: dict[str, str | None] = {}
        if filesystem.exists(marker_path):
            previous_marker = self._read_marker(filesystem, marker_path)
            if previous_marker.get("platform") != platform:
                raise AnchorError(f"Skill marker at {destination} is for a different platform.")
            previous_files = self._marker_files(previous_marker, marker_path)
            self._require_unmodified_assets(
                filesystem,
                destination,
                previous_files,
                force=force,
                operation="update",
            )

        asset_files = self._asset_files(runtime=runtime, npx_package=npx_package)
        new_file_digests = {
            path.as_posix(): self._digest(content)
            for path, content in asset_files
        }
        for relative_path, content in asset_files:
            target = self._safe_child(filesystem, destination, relative_path)
            self._write_bytes(filesystem, target, content)

        for relative_name in previous_files:
            if relative_name in new_file_digests:
                continue
            target = self._safe_child(filesystem, destination, Path(relative_name))
            if filesystem.exists(target) and filesystem.is_file(target):
                filesystem.unlink(target)
            filesystem.remove_empty_parents(target.parent, destination)

        installed_version = self._installed_version()
        marker = {
            "schema_version": 2,
            "skill": SKILL_NAME,
            "platform": platform,
            "scope": "project" if project_scoped else "user-global",
            "version": installed_version,
            "runtime": runtime,
            "files": [
                {"path": path.as_posix(), "sha256": new_file_digests[path.as_posix()]}
                for path, _ in asset_files
            ],
        }
        if runtime == SKILL_RUNTIME_NPX:
            marker["npx_package"] = npx_package
        self._write_text(filesystem, marker_path, json.dumps(marker, indent=2, sort_keys=True) + "\n")
        return SkillInstallation(
            destination=destination,
            platform=platform,
            project_scoped=project_scoped,
            version=installed_version,
            runtime=runtime,
        )

    def uninstall(
        self,
        *,
        platform: str,
        project_scoped: bool,
        force: bool = False,
    ) -> SkillInstallation:
        filesystem = self._filesystem_for(project_scoped)
        destination = self.destination_for(platform=platform, project_scoped=project_scoped)
        marker_path = self._safe_child(filesystem, destination, Path(_MARKER_NAME))
        if not filesystem.exists(marker_path):
            raise AnchorError(f"No AnchorLoop skill installation is recorded at {destination}.")

        marker = self._read_marker(filesystem, marker_path)
        recorded_platform = marker.get("platform")
        if recorded_platform != platform:
            raise AnchorError(f"Skill marker at {destination} is for platform '{recorded_platform}', not '{platform}'.")

        paths = self._marker_files(marker, marker_path)
        self._require_unmodified_assets(filesystem, destination, paths, force=force, operation="uninstall")
        for relative_name in sorted(paths, key=lambda value: value.count("/"), reverse=True):
            target = self._safe_child(filesystem, destination, Path(relative_name))
            if filesystem.exists(target) and filesystem.is_file(target):
                filesystem.unlink(target)
            filesystem.remove_empty_parents(target.parent, destination)

        filesystem.unlink(marker_path)
        filesystem.remove_empty_parents(destination, destination.parent)
        return SkillInstallation(
            destination=destination,
            platform=platform,
            project_scoped=project_scoped,
            version=str(marker.get("version", "unknown")),
            runtime=str(marker.get("runtime", SKILL_RUNTIME_ANCHOR)),
        )

    def installation_status(self, *, platform: str, project_scoped: bool) -> dict[str, Any]:
        filesystem = self._filesystem_for(project_scoped)
        destination = self.destination_for(platform=platform, project_scoped=project_scoped)
        marker_path = self._safe_child(filesystem, destination, Path(_MARKER_NAME))
        if not filesystem.exists(marker_path):
            return {"installed": False, "destination": str(destination)}
        marker = self._read_marker(filesystem, marker_path)
        integrity = "ok"
        bundle_current = False
        try:
            recorded_files = self._marker_files(marker, marker_path)
            self._require_unmodified_assets(
                filesystem,
                destination,
                recorded_files,
                force=False,
                operation="inspect",
            )
            runtime = str(marker.get("runtime", SKILL_RUNTIME_ANCHOR))
            npx_package = marker.get("npx_package")
            self._validate_runtime(runtime, npx_package if isinstance(npx_package, str) else None)
            current_files = {
                path.as_posix(): self._digest(content)
                for path, content in self._asset_files(runtime=runtime, npx_package=npx_package)
            }
            bundle_current = recorded_files == current_files
        except AnchorError:
            integrity = "modified"
        return {
            "installed": True,
            "destination": str(destination),
            "platform": marker.get("platform"),
            "version": marker.get("version"),
            "current_version": self._installed_version(),
            "integrity": integrity,
            "bundle_current": bundle_current,
            "up_to_date": (
                marker.get("version") == self._installed_version()
                and integrity == "ok"
                and bundle_current
            ),
            "runtime": marker.get("runtime", SKILL_RUNTIME_ANCHOR),
            "npx_package": marker.get("npx_package"),
        }

    @staticmethod
    def _validate_platform(platform: str) -> None:
        if platform not in SUPPORTED_PLATFORMS:
            supported = ", ".join(SUPPORTED_PLATFORMS)
            raise AnchorError(f"Skill platform must be one of: {supported}.")

    @staticmethod
    def _validate_runtime(runtime: str, npx_package: str | None) -> None:
        if runtime not in SUPPORTED_SKILL_RUNTIMES:
            supported = ", ".join(SUPPORTED_SKILL_RUNTIMES)
            raise AnchorError(f"Skill runtime must be one of: {supported}.")
        if runtime == SKILL_RUNTIME_ANCHOR:
            if npx_package is not None:
                raise AnchorError("An npm package can be set only for the npx skill runtime.")
            return
        if not npx_package or not _NPX_PACKAGE_PATTERN.fullmatch(npx_package):
            raise AnchorError(
                "The npx skill runtime requires a pinned npm package such as anchorloop@0.1.0."
            )

    @staticmethod
    def _installed_version() -> str:
        try:
            return version("anchorloop")
        except PackageNotFoundError:
            return "0.1.0"

    @staticmethod
    def _asset_files(*, runtime: str, npx_package: str | None) -> list[tuple[Path, bytes]]:
        root = files("anchorloop").joinpath("skills", SKILL_NAME)
        if not root.is_dir():
            raise AnchorError("AnchorLoop skill assets are missing from this installation.")

        assets: list[tuple[Path, bytes]] = []
        command = "anchor" if runtime == SKILL_RUNTIME_ANCHOR else f"npx --yes {npx_package}"

        def collect(directory: Any, relative_root: Path) -> None:
            for child in sorted(directory.iterdir(), key=lambda item: item.name):
                relative_path = relative_root / child.name
                if child.is_dir():
                    collect(child, relative_path)
                else:
                    content = child.read_bytes()
                    if relative_path.suffix == ".md":
                        content = content.decode("utf-8").replace("{{ANCHOR_COMMAND}}", command).encode("utf-8")
                    assets.append((relative_path, content))

        collect(root, Path())
        return assets

    @staticmethod
    def _safe_child(filesystem: SafeProjectFS, root: Path, relative_path: Path) -> Path:
        if (
            relative_path.is_absolute()
            or relative_path.drive
            or relative_path.root
            or ".." in relative_path.parts
        ):
            raise AnchorError("Skill asset path escapes its installation directory.")
        candidate = root / relative_path
        if root != candidate.parent and root not in candidate.parents:
            raise AnchorError("Skill asset path escapes its installation directory.")
        return filesystem.validate(candidate)

    @staticmethod
    def _write_text(filesystem: SafeProjectFS, path: Path, content: str) -> None:
        SkillInstaller._write_bytes(filesystem, path, content.encode("utf-8"))

    @staticmethod
    def _write_bytes(filesystem: SafeProjectFS, path: Path, content: bytes) -> None:
        filesystem.atomic_write_bytes(path, content)

    @staticmethod
    def _read_marker(filesystem: SafeProjectFS, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(filesystem.read_text(path))
        except (AnchorError, UnicodeDecodeError, json.JSONDecodeError) as error:
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
        filesystem: SafeProjectFS,
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
            target = self._safe_child(filesystem, destination, Path(relative_name))
            if not filesystem.exists(target):
                modified.append(relative_name)
                continue
            if not filesystem.is_file(target) or expected_digest is None:
                modified.append(relative_name)
                continue
            try:
                actual_digest = self._digest(filesystem.read_bytes(target))
            except AnchorError:
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
