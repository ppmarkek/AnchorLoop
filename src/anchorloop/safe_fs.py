from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


class AnchorError(Exception):
    """Raised when an Anchor command would break an explicit workflow rule."""


class SafeProjectFS:
    """Confine AnchorLoop-owned files to one root without following links.

    The project directory itself can be reached through a user-selected link: it
    is resolved once when the boundary is created. Every managed descendant is
    then kept lexical to that resolved root and any existing symlink or Windows
    reparse-point component is rejected.
    """

    def __init__(self, root: Path) -> None:
        # Keep the spelling selected by the caller as well as the resolved
        # boundary.  Windows can expose the same directory through an 8.3
        # alias (for example RUNNER~1) while ``resolve()`` returns its long
        # name.  Callers may retain that original spelling when constructing
        # descendants, so validate their lexical suffix against either known
        # spelling and always operate beneath the resolved boundary.
        self._selected_root = Path(os.path.abspath(root))
        self.root = self._selected_root.resolve()

    def path(self, *parts: str | Path) -> Path:
        candidate = self.root
        for part in parts:
            relative = Path(part)
            if relative.is_absolute() or relative.drive or relative.root or ".." in relative.parts:
                raise AnchorError("Managed path escapes the project root.")
            candidate /= relative
        return self.validate(candidate)

    def validate(self, path: Path, *, require_exists: bool = False) -> Path:
        """Validate a managed path without dereferencing a symlink boundary."""

        candidate = Path(path)
        if not candidate.is_absolute():
            if candidate.drive or candidate.root:
                raise AnchorError("Managed path escapes the project root.")
            candidate = self.root / candidate
        relative = self._relative_to_root(candidate)
        if ".." in relative.parts:
            raise AnchorError("Managed path escapes the project root.")

        # Rebase descendants supplied through the selected spelling onto the
        # immutable resolved boundary.  This does not dereference descendant
        # links; _validate_existing_components() still rejects every symlink
        # or reparse-point below the boundary before any managed operation.
        candidate = self.root / relative

        self._validate_existing_components(relative)
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(self.root)
        except (OSError, RuntimeError, ValueError) as error:
            raise AnchorError("Managed path resolves outside the project root.") from error

        if require_exists and self._lstat(candidate) is None:
            raise AnchorError(f"Managed path does not exist: {candidate}")
        return candidate

    def _relative_to_root(self, candidate: Path) -> Path:
        for root in (self.root, self._selected_root):
            try:
                return candidate.relative_to(root)
            except ValueError:
                continue
        raise AnchorError("Managed path escapes the project root.")

    def exists(self, path: Path) -> bool:
        candidate = self.validate(path)
        return self._lstat(candidate) is not None

    def is_file(self, path: Path) -> bool:
        candidate = self.validate(path)
        metadata = self._lstat(candidate)
        return metadata is not None and stat.S_ISREG(metadata.st_mode)

    def is_dir(self, path: Path) -> bool:
        candidate = self.validate(path)
        metadata = self._lstat(candidate)
        return metadata is not None and stat.S_ISDIR(metadata.st_mode)

    def glob(self, path: Path, pattern: str) -> list[Path]:
        directory = self.validate(path, require_exists=True)
        self._require_directory(directory, self._lstat(directory))
        try:
            children = list(directory.iterdir())
        except OSError as error:
            raise AnchorError(f"Cannot list managed directory: {directory}") from error
        result = []
        for child in children:
            self.validate(child, require_exists=True)
            if child.match(pattern):
                result.append(child)
        return result

    def ensure_directory(self, path: Path) -> Path:
        candidate = self.validate(path)
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as error:  # Defensive: validate() already checks this.
            raise AnchorError("Managed directory escapes the project root.") from error

        self._ensure_root_directory()
        current = self.root
        for part in relative.parts:
            current /= part
            metadata = self._lstat(current)
            if metadata is None:
                try:
                    current.mkdir()
                except FileExistsError:
                    metadata = self._lstat(current)
                    if metadata is None:
                        raise
                else:
                    metadata = self._lstat(current)
            self._require_directory(current, metadata)
        return candidate

    def read_bytes(self, path: Path) -> bytes:
        candidate = self.validate(path, require_exists=True)
        metadata = self._lstat(candidate)
        self._require_regular_file(candidate, metadata)
        descriptor = self._open_no_follow(candidate, os.O_RDONLY)
        try:
            with os.fdopen(descriptor, "rb") as stream:
                return stream.read()
        except OSError as error:
            raise AnchorError(f"Cannot read managed file: {candidate}") from error

    def read_text(self, path: Path, *, encoding: str = "utf-8") -> str:
        try:
            return self.read_bytes(path).decode(encoding)
        except UnicodeDecodeError as error:
            raise AnchorError(f"Cannot decode managed file: {path}") from error

    def mode_for_write(self, path: Path) -> int:
        """Return the mode a write to ``path`` must carry.

        Replacing a file with ``os.replace`` replaces its inode as well.  Keep
        the existing permission bits when there is a regular-file target, and
        make the policy for a new managed file explicit instead of inheriting
        ``mkstemp``'s private 0600 default everywhere.  The returned mode is
        always the mode that this platform can round-trip through ``stat``;
        this lets durable transaction journals compare it safely on Windows.
        """

        candidate = self.validate(path)
        metadata = self._lstat(candidate)
        if metadata is not None:
            self._require_regular_file(candidate, metadata)
            return stat.S_IMODE(metadata.st_mode)
        return self._default_file_mode(candidate)

    def atomic_write_bytes(self, path: Path, content: bytes, *, mode: int | None = None) -> None:
        candidate = self.validate(path)
        self.ensure_directory(candidate.parent)
        target_mode = self.mode_for_write(candidate) if mode is None else self._validate_file_mode(mode)

        descriptor: int | None = None
        temporary: Path | None = None
        temporary_stat: os.stat_result | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{candidate.name}.", suffix=".tmp", dir=str(candidate.parent)
            )
            temporary = Path(temporary_name)
            temporary_stat = os.fstat(descriptor)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                self._set_temporary_mode(stream.fileno(), temporary, temporary_stat, target_mode)
                os.fsync(stream.fileno())

            self._require_unchanged_temporary(temporary, temporary_stat)
            self.validate(candidate)
            self._require_write_target(candidate)
            os.replace(temporary, candidate)
            temporary = None
            self._fsync_directory(candidate.parent)
        except OSError as error:
            raise AnchorError(f"Cannot write managed file: {candidate}") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    def atomic_write_text(
        self,
        path: Path,
        content: str,
        *,
        encoding: str = "utf-8",
        mode: int | None = None,
    ) -> None:
        self.atomic_write_bytes(path, content.encode(encoding), mode=mode)

    def append_text(self, path: Path, content: str, *, encoding: str = "utf-8") -> None:
        candidate = self.validate(path)
        self.ensure_directory(candidate.parent)
        target_mode = self.mode_for_write(candidate)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        descriptor = self._open_no_follow(candidate, flags, mode=target_mode)
        try:
            with os.fdopen(descriptor, "a", encoding=encoding) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise AnchorError(f"Cannot append managed file: {candidate}") from error

    def unlink(self, path: Path, *, missing_ok: bool = False) -> None:
        candidate = self.validate(path)
        metadata = self._lstat(candidate)
        if metadata is None:
            if missing_ok:
                return
            raise AnchorError(f"Managed path does not exist: {candidate}")
        self._require_regular_file(candidate, metadata)
        try:
            os.unlink(candidate)
            self._fsync_directory(candidate.parent)
        except OSError as error:
            raise AnchorError(f"Cannot remove managed file: {candidate}") from error

    def remove_empty_parents(self, path: Path, stop_before: Path) -> None:
        current = self.validate(path)
        stop = self.validate(stop_before)
        try:
            current.relative_to(stop)
        except ValueError as error:
            raise AnchorError("Managed cleanup path escapes its installation root.") from error

        while current != stop:
            metadata = self._lstat(current)
            if metadata is None:
                current = current.parent
                continue
            self._require_directory(current, metadata)
            try:
                os.rmdir(current)
            except OSError:
                return
            parent = current.parent
            self._fsync_directory(parent)
            current = parent

    def _validate_existing_components(self, relative: Path) -> None:
        root_metadata = self._lstat(self.root)
        if root_metadata is not None:
            self._require_directory(self.root, root_metadata)

        current = self.root
        parts = relative.parts
        for index, part in enumerate(parts):
            current /= part
            metadata = self._lstat(current)
            if metadata is None:
                return
            self._reject_link(current, metadata)
            if index < len(parts) - 1:
                self._require_directory(current, metadata)

    def _ensure_root_directory(self) -> None:
        metadata = self._lstat(self.root)
        if metadata is None:
            try:
                self.root.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise AnchorError(f"Cannot create project directory: {self.root}") from error
            metadata = self._lstat(self.root)
        self._require_directory(self.root, metadata)

    def _require_write_target(self, path: Path, *, allow_missing: bool = True) -> None:
        metadata = self._lstat(path)
        if metadata is None:
            if allow_missing:
                return
            raise AnchorError(f"Managed path does not exist: {path}")
        self._require_regular_file(path, metadata)

    def _require_regular_file(self, path: Path, metadata: os.stat_result | None) -> None:
        if metadata is None:
            raise AnchorError(f"Managed path does not exist: {path}")
        self._reject_link(path, metadata)
        if not stat.S_ISREG(metadata.st_mode):
            raise AnchorError(f"Managed path must be a regular file: {path}")

    def _require_directory(self, path: Path, metadata: os.stat_result | None) -> None:
        if metadata is None:
            raise AnchorError(f"Managed directory does not exist: {path}")
        self._reject_link(path, metadata)
        if not stat.S_ISDIR(metadata.st_mode):
            raise AnchorError(f"Managed path must be a directory: {path}")

    @staticmethod
    def _lstat(path: Path) -> os.stat_result | None:
        try:
            return os.lstat(path)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise AnchorError(f"Cannot inspect managed path: {path}") from error

    @staticmethod
    def _reject_link(path: Path, metadata: os.stat_result) -> None:
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or (reparse_point and attributes & reparse_point):
            raise AnchorError(f"Refusing symlink or reparse-point managed path: {path}")

    def _open_no_follow(self, path: Path, flags: int, *, mode: int = 0o600) -> int:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        try:
            return os.open(path, flags | no_follow, mode)
        except OSError as error:
            raise AnchorError(f"Cannot safely open managed file: {path}") from error

    def _default_file_mode(self, path: Path) -> int:
        if os.name == "nt":
            # Python's POSIX-looking chmod bits do not model Windows ACLs.  A
            # new regular file round-trips through stat as 0666 (or 0444 when
            # read-only), so record that effective mode rather than a 0600 or
            # 0644 request that a recovery comparison can never observe.
            # Native ACL inheritance remains responsible for access control.
            return 0o666

        relative = path.relative_to(self.root)
        if self.root.name == ".anchor" or (relative.parts and relative.parts[0] == ".anchor"):
            # State, journals, locks, and event evidence may contain local
            # workflow information; do not make a new state file group/world
            # readable merely because it is written atomically.
            return 0o600
        # Repository metadata and portable skill assets should retain the
        # conventional shareable-file default instead of mkstemp's 0600.
        return 0o644

    @staticmethod
    def _validate_file_mode(mode: int) -> int:
        if not isinstance(mode, int) or isinstance(mode, bool) or mode < 0 or mode > 0o7777:
            raise AnchorError("Managed file mode must be a permission bitmask.")
        return mode

    @staticmethod
    def _set_temporary_mode(
        descriptor: int,
        path: Path,
        expected: os.stat_result | None,
        mode: int,
    ) -> None:
        """Set permissions without opening a replacement path when possible."""

        try:
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                fchmod(descriptor, mode)
                return

            # Windows builds without fchmod need a path-based fallback.  Check
            # identity both before and after so a swapped temp name is never
            # chmod'ed and committed.
            SafeProjectFS._require_unchanged_temporary(path, expected)
            os.chmod(path, mode)
            SafeProjectFS._require_unchanged_temporary(path, expected)
        except OSError as error:
            raise AnchorError(f"Cannot set managed file permissions: {path}") from error

    @staticmethod
    def _require_unchanged_temporary(path: Path, expected: os.stat_result | None) -> None:
        if expected is None:
            raise AnchorError("Cannot validate temporary managed file.")
        actual = SafeProjectFS._lstat(path)
        if actual is None or not stat.S_ISREG(actual.st_mode):
            raise AnchorError("Temporary managed file was replaced before it could be committed.")
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise AnchorError("Temporary managed file was replaced before it could be committed.")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
