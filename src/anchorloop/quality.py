from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any


_SKIP_DIRECTORIES = {".anchor", ".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", "graphify-out"}
_TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".rb", ".php", ".sh", ".json", ".yaml", ".yml", ".toml", ".env", ".md"}
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][^\"']{8,}[\"']"
)


class GitInspectionError(RuntimeError):
    """A required Git working-tree query could not be completed."""


def run_precommit(root: Path, *, active_categories: set[str]) -> dict[str, Any]:
    """Run small, local checks that are safe before project-specific tools exist."""

    findings: list[dict[str, str]] = []
    checks: list[dict[str, str]] = []
    starting_fingerprint = workspace_fingerprint(root)
    files = list(_source_files(root))

    syntax_failures = _python_syntax_failures(root, files)
    if syntax_failures:
        findings.extend(syntax_failures)
        checks.append({"name": "python-syntax", "status": "failed"})
    else:
        checks.append({"name": "python-syntax", "status": "passed"})

    if "security" not in active_categories:
        checks.append(
            {
                "name": "secret-baseline",
                "status": "not-run",
                "detail": "security rule is not approved for this task",
            }
        )
    else:
        secret_findings = _secret_findings(root, files)
        if secret_findings:
            findings.extend(secret_findings)
            checks.append({"name": "secret-baseline", "status": "failed"})
        else:
            checks.append({"name": "secret-baseline", "status": "passed"})

    whitespace_checks = (
        _git_whitespace_check(root, ("diff", "--check"), "git-diff-check"),
        _git_whitespace_check(root, ("diff", "--cached", "--check"), "git-cached-diff-check"),
    )
    checks.extend(whitespace_checks)
    for check in whitespace_checks:
        if check["status"] == "failed":
            findings.append(
                {
                    "category": "whitespace",
                    "location": check["name"],
                    "message": check.get("detail", "git diff --check failed"),
                }
            )

    ending_fingerprint = workspace_fingerprint(root)
    if starting_fingerprint["digest"] != ending_fingerprint["digest"]:
        findings.append(
            {
                "category": "workspace",
                "location": "working-tree",
                "message": "The workspace changed while the quality gate was running. Rerun pre-commit.",
            }
        )
        checks.append({"name": "workspace-stability", "status": "failed"})
    else:
        checks.append({"name": "workspace-stability", "status": "passed"})

    return {
        "status": "blocked" if findings or any(check["status"] == "failed" for check in checks) else "passed",
        "checks": checks,
        "findings": findings,
        "workspace_fingerprint": ending_fingerprint,
        "advisories": [
            "No project-specific formatter, linter, type checker, test runner, or dependency scanner is configured yet.",
            "DRY, KISS, YAGNI, SOLID, and architecture findings require concrete diff evidence and engineer review.",
        ],
    }


def workspace_fingerprint(root: Path) -> dict[str, Any]:
    """Return a deterministic snapshot of the checked workspace state.

    Verification is bound to the materialized files, not Git metadata. In a
    Git repository tracked and untracked (non-ignored) paths are enumerated by
    Git, then read from the working tree. HEAD/index/diff state is recorded in
    a separate diagnostic digest so a metadata-only commit does not invalidate
    otherwise identical quality evidence.
    """

    return _workspace_fingerprint(root.resolve(), ancestors=frozenset())


def _workspace_fingerprint(root: Path, *, ancestors: frozenset[str]) -> dict[str, Any]:
    """Fingerprint one materialized tree, recursively including submodules."""

    identity = os.path.normcase(str(root.resolve()))
    if identity in ancestors:
        digest = hashlib.sha256(b"anchorloop-workspace-v3\0submodule-cycle\0").hexdigest()
        return {
            "algorithm": "sha256",
            "format_version": 3,
            "digest": f"sha256:{digest}",
            "content_digest": f"sha256:{digest}",
            "git_state_digest": None,
            "source": "submodule-cycle",
            "files": 0,
            "head": None,
        }

    descendants = ancestors | {identity}
    git_entries = _git_materialized_paths(root, ancestors=descendants)
    if git_entries is not None:
        git_paths, submodules = git_entries
        head, git_state_digest = _git_state_diagnostics(root)
        return _materialized_fingerprint(
            root,
            git_paths,
            submodules=submodules,
            source="git-materialized",
            head=head,
            git_state_digest=git_state_digest,
        )
    return _materialized_fingerprint(
        root,
        sorted(_fingerprint_files(root), key=lambda path: path.relative_to(root).as_posix()),
        submodules=[],
        source="filesystem",
        head=None,
        git_state_digest=None,
    )


def _materialized_fingerprint(
    root: Path,
    files: list[Path],
    *,
    submodules: list[dict[str, Any]],
    source: str,
    head: str | None,
    git_state_digest: str | None,
) -> dict[str, Any]:
    digest = hashlib.sha256()
    digest.update(b"anchorloop-workspace-v3\0materialized-tree\0")
    for path in files:
        _update_digest_with_file(digest, root, path)
    for submodule in submodules:
        _update_digest_value(digest, b"entry", b"git-submodule")
        _update_digest_value(digest, b"path", submodule["path"])
        _update_digest_value(digest, b"state", submodule["state"])
        if submodule.get("content_digest") is not None:
            _update_digest_value(digest, b"content-digest", submodule["content_digest"])
        else:
            # An uninitialized or unsafe submodule has no materialized tree to
            # read, so bind the evidence to the tracked gitlink instead.
            _update_digest_value(digest, b"index-oid", submodule["index_oid"])
    return {
        "algorithm": "sha256",
        "format_version": 3,
        "digest": f"sha256:{digest.hexdigest()}",
        "content_digest": f"sha256:{digest.hexdigest()}",
        "git_state_digest": git_state_digest,
        "source": source,
        "files": len(files)
        + sum(max(1, int(submodule.get("files", 0))) for submodule in submodules),
        "head": head,
    }


def _git_materialized_paths(
    root: Path,
    *,
    ancestors: frozenset[str],
) -> tuple[list[Path], list[dict[str, Any]]] | None:
    if not (root / ".git").exists():
        return None

    listed = _git_bytes(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--")
    if listed is None:
        return None
    staged = _git_bytes(root, "ls-files", "--stage", "-z", "--")
    if staged is None:
        return None
    submodule_names: dict[str, bytes] = {}
    for record in staged.split(b"\0"):
        if not record or b"\t" not in record:
            continue
        metadata, encoded_name = record.split(b"\t", 1)
        fields = metadata.split()
        if len(fields) >= 2 and fields[0] == b"160000":
            submodule_names[
                encoded_name.decode("utf-8", errors="surrogateescape")
            ] = fields[1]
    paths: list[Path] = []
    seen: set[str] = set()
    for encoded_name in listed.split(b"\0"):
        if not encoded_name:
            continue
        name = encoded_name.decode("utf-8", errors="surrogateescape")
        if name in seen:
            continue
        seen.add(name)
        if name in submodule_names:
            continue
        path = root / name
        if _is_fingerprintable_path(path) and not _is_anchor_owned_path(root, path):
            paths.append(path)
    submodules: list[dict[str, Any]] = []
    for name in sorted(submodule_names):
        encoded_name = name.encode("utf-8", errors="surrogateescape")
        index_oid = submodule_names[name]
        submodule_path = root / name
        head_result = _git_bytes(root, "-C", name, "rev-parse", "--verify", "HEAD")
        status_result = _git_bytes(root, "-C", name, "status", "--porcelain=v1", "-z")
        head = head_result if head_result is not None else b"<missing>"
        status = status_result if status_result is not None else b"<unavailable>"
        record: dict[str, Any] = {
            "path": encoded_name,
            "index_oid": index_oid,
            "head": head.strip(),
            "status": status,
            "files": 0,
            "content_digest": None,
        }
        try:
            resolved_submodule = submodule_path.resolve(strict=True)
            resolved_submodule.relative_to(root)
            submodule_identity = os.path.normcase(str(resolved_submodule))
            if not resolved_submodule.is_dir():
                record["state"] = b"uninitialized"
            elif submodule_identity in ancestors:
                record["state"] = b"cycle"
            else:
                nested = _workspace_fingerprint(resolved_submodule, ancestors=ancestors)
                record["state"] = (
                    b"materialized-git"
                    if (resolved_submodule / ".git").exists()
                    else b"materialized-filesystem"
                )
                record["content_digest"] = nested["content_digest"].encode("ascii")
                record["files"] = nested["files"]
        except (OSError, ValueError):
            record["state"] = b"uninitialized-or-unsafe"
        submodules.append(record)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix()), submodules


def _git_state_diagnostics(root: Path) -> tuple[str | None, str | None]:
    """Return non-gating Git diagnostics for audit and troubleshooting."""

    head = _git_bytes(root, "rev-parse", "--verify", "HEAD")
    staged = _git_bytes(
        root,
        "diff",
        "--binary",
        "--cached",
        "--",
        ".",
        ":(exclude).anchor/**",
    )
    unstaged = _git_bytes(
        root,
        "diff",
        "--binary",
        "--",
        ".",
        ":(exclude).anchor/**",
    )
    if staged is None or unstaged is None:
        return None, None

    digest = hashlib.sha256()
    digest.update(b"anchorloop-git-state-v1\0")
    _update_digest_value(digest, b"head", head or b"<unborn>")
    _update_digest_value(digest, b"staged", staged)
    _update_digest_value(digest, b"unstaged", unstaged)
    return (
        head.decode("utf-8", errors="replace").strip() if head else None,
        f"sha256:{digest.hexdigest()}",
    )


def _git_bytes(root: Path, *arguments: str) -> bytes | None:
    try:
        process = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if process.returncode != 0:
        return None
    return process.stdout


def _update_digest_value(digest: Any, label: bytes, value: bytes) -> None:
    digest.update(label)
    digest.update(b"\0")
    digest.update(str(len(value)).encode("ascii"))
    digest.update(b"\0")
    digest.update(value)
    digest.update(b"\0")


def _update_digest_with_file(digest: Any, root: Path, path: Path) -> None:
    relative_path = path.relative_to(root).as_posix().encode("utf-8", errors="surrogateescape")
    try:
        metadata = os.lstat(path)
    except OSError:
        _update_digest_value(digest, b"entry", b"unreadable")
        _update_digest_value(digest, b"path", relative_path)
        return

    mode = str(stat.S_IMODE(metadata.st_mode)).encode("ascii")
    if stat.S_ISLNK(metadata.st_mode):
        try:
            target = os.readlink(path).encode("utf-8", errors="surrogateescape")
        except OSError:
            target = b"<unreadable>"
        _update_digest_value(digest, b"entry", b"symlink")
        _update_digest_value(digest, b"path", relative_path)
        _update_digest_value(digest, b"mode", mode)
        _update_digest_value(digest, b"target", target)
        return

    if not stat.S_ISREG(metadata.st_mode):
        _update_digest_value(digest, b"entry", b"unsupported")
        _update_digest_value(digest, b"path", relative_path)
        _update_digest_value(digest, b"mode", mode)
        return

    file_digest = hashlib.sha256()
    size = 0
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise OSError("fingerprint target changed while it was opened")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                file_digest.update(chunk)
    except OSError:
        _update_digest_value(digest, b"entry", b"unreadable")
        _update_digest_value(digest, b"path", relative_path)
        _update_digest_value(digest, b"mode", mode)
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)

    _update_digest_value(digest, b"entry", b"file")
    _update_digest_value(digest, b"path", relative_path)
    _update_digest_value(digest, b"mode", mode)
    _update_digest_value(digest, b"size", str(size).encode("ascii"))
    _update_digest_value(digest, b"content-sha256", file_digest.digest())


def _fingerprint_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if _is_fingerprintable_path(path)
        and not any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts)
    ]


def _is_fingerprintable_path(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _is_anchor_owned_path(root: Path, path: Path) -> bool:
    try:
        return path.relative_to(root).parts[:1] == (".anchor",)
    except ValueError:
        return False


def _source_files(root: Path) -> list[Path]:
    if (root / ".git").exists():
        changed = _git_changed_paths(root)
        return [path for path in changed if _is_supported_source_file(root, path)]

    return [path for path in root.rglob("*") if _is_supported_source_file(root, path)]


def git_changed_path_names(root: Path, *, strict: bool = False) -> list[str]:
    """Return normalized changed paths, including deleted files."""

    git_root = _git_bytes(root, "rev-parse", "--show-toplevel")
    if git_root is None:
        if strict:
            raise GitInspectionError(
                "Required Git inspection failed: git rev-parse --show-toplevel"
            )
        return []
    commands = (
        ("diff", "--relative", "--no-renames", "--name-only", "-z", "--"),
        ("diff", "--cached", "--relative", "--no-renames", "--name-only", "-z", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z", "--"),
    )
    paths: set[str] = set()
    for arguments in commands:
        output = _git_bytes(root, *arguments)
        if output is None:
            if strict:
                command = "git " + " ".join(arguments)
                raise GitInspectionError(f"Required Git inspection failed: {command}")
            continue
        for encoded_name in output.split(b"\0"):
            if not encoded_name:
                continue
            name = encoded_name.decode(
                "utf-8", errors="surrogateescape"
            ).replace("\\", "/")
            while name.startswith("./"):
                name = name[2:]
            if not name or name == ".anchor" or name.startswith(".anchor/"):
                continue
            paths.add(name)
    return sorted(paths)


def _git_changed_paths(root: Path) -> list[Path]:
    paths = [
        root / relative_name
        for relative_name in git_changed_path_names(root)
    ]
    return [path for path in paths if _is_regular_file(path)]


def _is_supported_source_file(root: Path, path: Path) -> bool:
    if not _is_regular_file(path) or any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts):
        return False
    return path.suffix.lower() in _TEXT_SUFFIXES or path.name.startswith(".env")


def _python_syntax_failures(root: Path, files: list[Path]) -> list[dict[str, str]]:
    failures = []
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (SyntaxError, UnicodeDecodeError) as error:
            line = getattr(error, "lineno", None)
            failures.append(
                {
                    "category": "syntax",
                    "location": _location(root, path, line),
                    "message": str(error),
                }
            )
    return failures


def _secret_findings(root: Path, files: list[Path]) -> list[dict[str, str]]:
    findings = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _PRIVATE_KEY.search(line) or _SECRET_ASSIGNMENT.search(line):
                findings.append(
                    {
                        "category": "secret",
                        "location": _location(root, path, line_number),
                        "message": "Possible hard-coded credential or private key.",
                    }
                )
    return findings


def _location(root: Path, path: Path, line: int | None = None) -> str:
    try:
        location = path.relative_to(root).as_posix()
    except ValueError:
        location = path.name
    return f"{location}:{line}" if line else location


def _git_whitespace_check(root: Path, arguments: tuple[str, ...], name: str) -> dict[str, str]:
    if not (root / ".git").exists():
        return {"name": name, "status": "not-run", "detail": "not a Git repository"}
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode == 0:
        return {"name": name, "status": "passed"}
    return {
        "name": name,
        "status": "failed",
        "detail": process.stdout.strip() or process.stderr.strip() or "git diff --check failed",
    }
