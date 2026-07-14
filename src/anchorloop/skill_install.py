from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from functools import wraps
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, TypeVar

from .project_lock import ProjectLock
from .safe_fs import AnchorError, SafeProjectFS
from .version import VERSION


SKILL_NAME = "anchorloop"


@dataclass(frozen=True)
class SkillPlatform:
    """One supported host's skill discovery locations."""

    key: str
    label: str
    project_parts: tuple[str, ...]
    user_parts: tuple[str, ...]


SKILL_PLATFORMS = {
    "agents": SkillPlatform(
        key="agents",
        label="Agent Skills standard",
        project_parts=(".agents",),
        user_parts=(".agents",),
    ),
    "codex": SkillPlatform(
        key="codex",
        label="Codex",
        project_parts=(".codex",),
        user_parts=(".codex",),
    ),
    "cursor": SkillPlatform(
        key="cursor",
        label="Cursor",
        project_parts=(".cursor",),
        user_parts=(".cursor",),
    ),
    "gemini": SkillPlatform(
        key="gemini",
        label="Gemini CLI",
        project_parts=(".gemini",),
        user_parts=(".gemini",),
    ),
    "claude": SkillPlatform(
        key="claude",
        label="Claude Code",
        project_parts=(".claude",),
        user_parts=(".claude",),
    ),
    "opencode": SkillPlatform(
        key="opencode",
        label="OpenCode",
        project_parts=(".opencode",),
        user_parts=(".config", "opencode"),
    ),
}
SUPPORTED_PLATFORMS = tuple(SKILL_PLATFORMS)
DEFAULT_PROJECT_PLATFORM = "agents"
SKILL_RUNTIME_ANCHOR = "anchor"
SKILL_RUNTIME_NPX = "npx"
SUPPORTED_SKILL_RUNTIMES = (SKILL_RUNTIME_ANCHOR, SKILL_RUNTIME_NPX)
_MARKER_NAME = ".anchorloop-skill.json"
_INSTALL_JOURNAL_NAME = "skill-install-journal.json"
_INSTALL_JOURNAL_SCHEMA = 1
_NPX_PACKAGE_PATTERN = re.compile(
    r"(?:[a-z0-9][a-z0-9._-]*|@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*)"
    r"@[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
)

_ReturnT = TypeVar("_ReturnT")


def platform_label(platform: str) -> str:
    """Return a human-readable host name after validating its identifier."""

    try:
        return SKILL_PLATFORMS[platform].label
    except KeyError as error:
        supported = ", ".join(SUPPORTED_PLATFORMS)
        raise AnchorError(f"Skill platform must be one of: {supported}.") from error


def _installation_lock_root(destination: Path) -> Path:
    lock_key = hashlib.sha256(
        os.path.normcase(str(destination)).encode("utf-8", errors="surrogatepass")
    ).hexdigest()
    return _private_install_lock_base() / lock_key


def _private_install_lock_base() -> Path:
    """Return a non-link, per-user temporary root for locks and journals."""

    base_name = "anchorloop-install-locks"
    if os.name != "nt" and hasattr(os, "getuid"):
        base_name = f"{base_name}-{os.getuid()}"
    base = Path(tempfile.gettempdir()) / base_name
    try:
        base.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as error:
        raise AnchorError(f"Cannot create AnchorLoop installer lock directory: {base}") from error

    try:
        metadata = os.lstat(base)
    except OSError as error:
        raise AnchorError(f"Cannot inspect AnchorLoop installer lock directory: {base}") from error
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or (reparse_flag and attributes & reparse_flag)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise AnchorError(f"AnchorLoop installer lock directory must be a real directory: {base}")

    if os.name != "nt" and hasattr(os, "getuid"):
        if metadata.st_uid != os.getuid():
            raise AnchorError(f"AnchorLoop installer lock directory is owned by another user: {base}")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            try:
                os.chmod(base, 0o700)
            except OSError as error:
                raise AnchorError(f"Cannot secure AnchorLoop installer lock directory: {base}") from error
    return base


def installation_locked(action: str) -> Callable[[Callable[..., _ReturnT]], Callable[..., _ReturnT]]:
    """Serialize install/update/uninstall/status for one exact destination."""

    def decorate(function: Callable[..., _ReturnT]) -> Callable[..., _ReturnT]:
        @wraps(function)
        def wrapped(self: "SkillInstaller", *args: Any, **kwargs: Any) -> _ReturnT:
            platform = kwargs.get("platform")
            project_scoped = kwargs.get("project_scoped")
            if not isinstance(platform, str) or not isinstance(project_scoped, bool):
                raise AnchorError("Skill installation scope and platform must be explicit.")
            destination = self.destination_for(platform=platform, project_scoped=project_scoped)
            lock_root = _installation_lock_root(destination)
            with ProjectLock(lock_root, purpose=f"skill.{action}"):
                return function(self, *args, **kwargs)

        return wrapped

    return decorate


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
            f"AnchorLoop skill {self.action} preview ({scope}, {platform_label(self.platform)})",
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
        definition = SKILL_PLATFORMS[platform]
        location = definition.project_parts if project_scoped else definition.user_parts
        return filesystem.path(*location, "skills", SKILL_NAME)

    def _filesystem_for(self, project_scoped: bool) -> SafeProjectFS:
        if project_scoped:
            return self._project_fs
        return SafeProjectFS(Path.home())

    @installation_locked("install")
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
        self._recover_pending_installation(
            filesystem,
            destination,
            platform=platform,
            project_scoped=project_scoped,
        )
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
        marker_content = (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8")
        journal = self._install_journal(
            destination=destination,
            platform=platform,
            project_scoped=project_scoped,
            version=installed_version,
            runtime=runtime,
            asset_files=asset_files,
            marker_content=marker_content,
            obsolete_files=[
                relative_name
                for relative_name in previous_files
                if relative_name not in new_file_digests
            ],
        )
        self._commit_install_journal(filesystem, destination, journal)
        return SkillInstallation(
            destination=destination,
            platform=platform,
            project_scoped=project_scoped,
            version=installed_version,
            runtime=runtime,
        )

    @installation_locked("uninstall")
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
        recovered = self._recover_pending_installation(
            filesystem,
            destination,
            platform=platform,
            project_scoped=project_scoped,
        )
        if (
            recovered is not None
            and recovered["action"] == "uninstall"
            and not filesystem.exists(marker_path)
        ):
            return SkillInstallation(
                destination=destination,
                platform=platform,
                project_scoped=project_scoped,
                version=str(recovered["version"]),
                runtime=str(recovered["runtime"]),
            )
        if not filesystem.exists(marker_path):
            raise AnchorError(f"No AnchorLoop skill installation is recorded at {destination}.")

        marker = self._read_marker(filesystem, marker_path)
        recorded_platform = marker.get("platform")
        if recorded_platform != platform:
            raise AnchorError(f"Skill marker at {destination} is for platform '{recorded_platform}', not '{platform}'.")

        paths = self._marker_files(marker, marker_path)
        self._require_unmodified_assets(filesystem, destination, paths, force=force, operation="uninstall")
        journal = self._uninstall_journal(
            destination=destination,
            platform=platform,
            project_scoped=project_scoped,
            version=str(marker.get("version", "unknown")),
            runtime=str(marker.get("runtime", SKILL_RUNTIME_ANCHOR)),
            owned_files=list(paths),
        )
        self._commit_install_journal(filesystem, destination, journal)
        return SkillInstallation(
            destination=destination,
            platform=platform,
            project_scoped=project_scoped,
            version=str(marker.get("version", "unknown")),
            runtime=str(marker.get("runtime", SKILL_RUNTIME_ANCHOR)),
        )

    @installation_locked("status")
    def installation_status(self, *, platform: str, project_scoped: bool) -> dict[str, Any]:
        filesystem = self._filesystem_for(project_scoped)
        destination = self.destination_for(platform=platform, project_scoped=project_scoped)
        marker_path = self._safe_child(filesystem, destination, Path(_MARKER_NAME))
        pending = self._pending_installation_status(
            filesystem,
            destination,
            platform=platform,
            project_scoped=project_scoped,
        )
        if pending is not None:
            return pending
        if not filesystem.exists(marker_path):
            return {
                "installed": False,
                "destination": str(destination),
                "recovery_pending": False,
            }
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
            "recovery_pending": False,
        }

    @staticmethod
    def _journal_context(destination: Path) -> tuple[SafeProjectFS, Path]:
        filesystem = SafeProjectFS(_installation_lock_root(destination))
        return filesystem, filesystem.path(".anchor", _INSTALL_JOURNAL_NAME)

    @staticmethod
    def _encoded_file(relative_path: str, content: bytes) -> dict[str, str]:
        return {
            "path": relative_path,
            "sha256": SkillInstaller._digest(content),
            "content_b64": base64.b64encode(content).decode("ascii"),
        }

    def _install_journal(
        self,
        *,
        destination: Path,
        platform: str,
        project_scoped: bool,
        version: str,
        runtime: str,
        asset_files: list[tuple[Path, bytes]],
        marker_content: bytes,
        obsolete_files: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": _INSTALL_JOURNAL_SCHEMA,
            "destination": str(destination),
            "action": "install",
            "platform": platform,
            "project_scoped": project_scoped,
            "version": version,
            "runtime": runtime,
            "writes": [
                self._encoded_file(path.as_posix(), content)
                for path, content in asset_files
            ],
            "deletes": sorted(obsolete_files),
            "marker": self._encoded_file(_MARKER_NAME, marker_content),
        }

    @staticmethod
    def _uninstall_journal(
        *,
        destination: Path,
        platform: str,
        project_scoped: bool,
        version: str,
        runtime: str,
        owned_files: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": _INSTALL_JOURNAL_SCHEMA,
            "destination": str(destination),
            "action": "uninstall",
            "platform": platform,
            "project_scoped": project_scoped,
            "version": version,
            "runtime": runtime,
            "writes": [],
            "deletes": sorted(owned_files, key=lambda value: value.count("/"), reverse=True),
            "marker": None,
        }

    def _commit_install_journal(
        self,
        filesystem: SafeProjectFS,
        destination: Path,
        journal: dict[str, Any],
    ) -> None:
        journal_filesystem, journal_path = self._journal_context(destination)
        if journal_filesystem.exists(journal_path):
            raise AnchorError(
                f"A pending AnchorLoop skill recovery already exists for {destination}. Retry the command."
            )
        self._decode_install_journal(journal, filesystem, destination)
        journal_filesystem.atomic_write_text(
            journal_path,
            json.dumps(journal, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        )
        try:
            self._apply_install_journal(filesystem, destination, journal)
        except BaseException:
            # The durable journal is intentionally retained. A later mutating
            # command will roll the exact intended operation forward.
            raise
        journal_filesystem.unlink(journal_path)

    def _recover_pending_installation(
        self,
        filesystem: SafeProjectFS,
        destination: Path,
        *,
        platform: str,
        project_scoped: bool,
    ) -> dict[str, Any] | None:
        journal_filesystem, journal_path = self._journal_context(destination)
        if not journal_filesystem.exists(journal_path):
            return None
        journal = self._read_install_journal(journal_filesystem, journal_path)
        self._require_journal_scope(
            journal,
            destination,
            platform=platform,
            project_scoped=project_scoped,
        )
        self._apply_install_journal(filesystem, destination, journal)
        journal_filesystem.unlink(journal_path)
        return journal

    def _pending_installation_status(
        self,
        filesystem: SafeProjectFS,
        destination: Path,
        *,
        platform: str,
        project_scoped: bool,
    ) -> dict[str, Any] | None:
        journal_filesystem, journal_path = self._journal_context(destination)
        if not journal_filesystem.exists(journal_path):
            return None
        try:
            journal = self._read_install_journal(journal_filesystem, journal_path)
            self._require_journal_scope(
                journal,
                destination,
                platform=platform,
                project_scoped=project_scoped,
            )
            self._decode_install_journal(journal, filesystem, destination)
            action = journal["action"]
            error = None
        except AnchorError as caught:
            action = "unknown"
            error = str(caught)
        status: dict[str, Any] = {
            "installed": filesystem.exists(self._safe_child(filesystem, destination, Path(_MARKER_NAME))),
            "destination": str(destination),
            "recovery_pending": True,
            "recovery_action": action,
            "recovery_journal": str(journal_path),
            "integrity": "pending-recovery",
            "up_to_date": False,
        }
        if error is not None:
            status["recovery_error"] = error
        return status

    @staticmethod
    def _read_install_journal(filesystem: SafeProjectFS, journal_path: Path) -> dict[str, Any]:
        try:
            journal = json.loads(filesystem.read_text(journal_path))
        except (AnchorError, json.JSONDecodeError) as error:
            raise AnchorError(f"Cannot read skill recovery journal at {journal_path}.") from error
        if not isinstance(journal, dict):
            raise AnchorError(f"Skill recovery journal at {journal_path} is invalid.")
        return journal

    @staticmethod
    def _require_journal_scope(
        journal: dict[str, Any],
        destination: Path,
        *,
        platform: str,
        project_scoped: bool,
    ) -> None:
        recorded_destination = journal.get("destination")
        if not isinstance(recorded_destination, str) or os.path.normcase(
            os.path.abspath(recorded_destination)
        ) != os.path.normcase(os.path.abspath(str(destination))):
            raise AnchorError("Skill recovery journal is for a different destination.")
        if journal.get("platform") != platform or journal.get("project_scoped") != project_scoped:
            raise AnchorError("Skill recovery journal is for a different installation scope.")

    def _decode_install_journal(
        self,
        journal: dict[str, Any],
        filesystem: SafeProjectFS,
        destination: Path,
    ) -> tuple[list[tuple[Path, bytes]], list[Path], bytes | None]:
        if journal.get("schema_version") != _INSTALL_JOURNAL_SCHEMA:
            raise AnchorError("Skill recovery journal schema is unsupported.")
        action = journal.get("action")
        if action not in {"install", "uninstall"}:
            raise AnchorError("Skill recovery journal action is invalid.")
        if journal.get("platform") not in SUPPORTED_PLATFORMS:
            raise AnchorError("Skill recovery journal platform is invalid.")
        if not isinstance(journal.get("project_scoped"), bool):
            raise AnchorError("Skill recovery journal scope is invalid.")
        if not isinstance(journal.get("version"), str) or not isinstance(journal.get("runtime"), str):
            raise AnchorError("Skill recovery journal metadata is invalid.")

        raw_writes = journal.get("writes")
        raw_deletes = journal.get("deletes")
        if not isinstance(raw_writes, list) or not isinstance(raw_deletes, list):
            raise AnchorError("Skill recovery journal operations are invalid.")

        writes: list[tuple[Path, bytes]] = []
        write_names: set[str] = set()
        for entry in raw_writes:
            relative_path, content = self._decode_journal_file(entry, filesystem, destination)
            name = relative_path.as_posix()
            if name == _MARKER_NAME or name in write_names:
                raise AnchorError("Skill recovery journal contains duplicate or reserved writes.")
            write_names.add(name)
            writes.append((relative_path, content))

        deletes: list[Path] = []
        delete_names: set[str] = set()
        for value in raw_deletes:
            if not isinstance(value, str):
                raise AnchorError("Skill recovery journal delete path is invalid.")
            relative_path = self._journal_relative_path(value, filesystem, destination)
            name = relative_path.as_posix()
            if name == _MARKER_NAME or name in delete_names or name in write_names:
                raise AnchorError("Skill recovery journal contains duplicate or conflicting deletes.")
            delete_names.add(name)
            deletes.append(relative_path)

        raw_marker = journal.get("marker")
        marker_content: bytes | None
        if action == "install":
            marker_path, marker_content = self._decode_journal_file(raw_marker, filesystem, destination)
            if marker_path.as_posix() != _MARKER_NAME:
                raise AnchorError("Skill recovery journal marker path is invalid.")
            try:
                marker = json.loads(marker_content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise AnchorError("Skill recovery journal marker content is invalid.") from error
            if not isinstance(marker, dict) or marker.get("skill") != SKILL_NAME:
                raise AnchorError("Skill recovery journal marker content is invalid.")
            expected_scope = "project" if journal["project_scoped"] else "user-global"
            if (
                marker.get("platform") != journal["platform"]
                or marker.get("scope") != expected_scope
                or marker.get("version") != journal["version"]
                or marker.get("runtime") != journal["runtime"]
            ):
                raise AnchorError("Skill recovery journal marker metadata does not match the operation.")
            marker_files = self._marker_files(marker, destination / _MARKER_NAME)
            expected_files = {
                relative_path.as_posix(): self._digest(content)
                for relative_path, content in writes
            }
            if marker_files != expected_files:
                raise AnchorError("Skill recovery journal marker does not match its writes.")
        else:
            if raw_marker is not None or writes:
                raise AnchorError("Skill uninstall recovery journal contains writes.")
            marker_content = None

        return writes, deletes, marker_content

    def _decode_journal_file(
        self,
        entry: Any,
        filesystem: SafeProjectFS,
        destination: Path,
    ) -> tuple[Path, bytes]:
        if not isinstance(entry, dict):
            raise AnchorError("Skill recovery journal file entry is invalid.")
        name = entry.get("path")
        encoded = entry.get("content_b64")
        digest = entry.get("sha256")
        if not isinstance(name, str) or not isinstance(encoded, str) or not isinstance(digest, str):
            raise AnchorError("Skill recovery journal file entry is invalid.")
        relative_path = self._journal_relative_path(name, filesystem, destination)
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as error:
            raise AnchorError("Skill recovery journal contains invalid encoded content.") from error
        if self._digest(content) != digest:
            raise AnchorError("Skill recovery journal content digest is invalid.")
        return relative_path, content

    def _journal_relative_path(
        self,
        value: str,
        filesystem: SafeProjectFS,
        destination: Path,
    ) -> Path:
        if not value or "\\" in value:
            raise AnchorError("Skill recovery journal path is invalid.")
        relative_path = Path(value)
        if relative_path.as_posix() != value or relative_path in {Path("."), Path("")}:
            raise AnchorError("Skill recovery journal path is invalid.")
        self._safe_child(filesystem, destination, relative_path)
        return relative_path

    def _apply_install_journal(
        self,
        filesystem: SafeProjectFS,
        destination: Path,
        journal: dict[str, Any],
    ) -> None:
        writes, deletes, marker_content = self._decode_install_journal(journal, filesystem, destination)
        marker_path = self._safe_child(filesystem, destination, Path(_MARKER_NAME))

        for relative_path, content in writes:
            target = self._safe_child(filesystem, destination, relative_path)
            self._write_bytes(filesystem, target, content)

        for relative_path in deletes:
            target = self._safe_child(filesystem, destination, relative_path)
            if filesystem.exists(target):
                if not filesystem.is_file(target):
                    raise AnchorError(f"Managed skill asset must be a regular file: {target}")
                filesystem.unlink(target)
            filesystem.remove_empty_parents(target.parent, destination)

        if journal["action"] == "install":
            assert marker_content is not None
            # The marker is the commit record and is deliberately written only
            # after every owned asset matches the journaled bundle.
            self._write_bytes(filesystem, marker_path, marker_content)
            return

        # During uninstall the old marker remains until all owned assets have
        # been removed, so an interrupted operation is never mistaken for a
        # completed removal.
        filesystem.unlink(marker_path, missing_ok=True)
        filesystem.remove_empty_parents(destination, filesystem.root)

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
        return VERSION

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
