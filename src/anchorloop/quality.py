from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SKIP_DIRECTORIES = {".anchor", ".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", "graphify-out"}
_TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".rb", ".php", ".sh", ".json", ".yaml", ".yml", ".toml", ".env", ".md"}
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][^\"']{8,}[\"']"
)
_TASK_BASELINE_MAX_ENTRIES = 100_000
_TASK_BASELINE_MAX_BYTES = 512 * 1024 * 1024
_HISTORY_SCAN_MAX_OBJECTS = 100_000
_HISTORY_SCAN_MAX_COMMITS = 1_000
_HISTORY_SCAN_MAX_BYTES = 64 * 1024 * 1024
_GIT_OBJECT_ID = re.compile(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class GitInspectionError(RuntimeError):
    """A required task-baseline query could not be completed safely."""


@dataclass
class _HistoryScanBudget:
    objects: int = 0
    bytes: int = 0


def run_precommit(
    root: Path,
    *,
    active_categories: set[str],
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run small, local checks that are safe before project-specific tools exist."""

    findings: list[dict[str, str]] = []
    checks: list[dict[str, str]] = []
    starting_fingerprint = workspace_fingerprint(root)
    documents = _source_documents(root, baseline=baseline)

    syntax_failures = _python_syntax_failures(documents)
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
        secret_findings = _secret_findings(
            _security_source_documents(root, baseline=baseline, documents=documents)
        )
        if secret_findings:
            findings.extend(secret_findings)
            checks.append({"name": "secret-baseline", "status": "failed"})
        else:
            checks.append({"name": "secret-baseline", "status": "passed"})

    whitespace_arguments: list[tuple[tuple[str, ...], str]] = []
    if isinstance(baseline, dict) and baseline.get("source") == "git":
        head = baseline.get("head")
        if not isinstance(head, str):
            raise GitInspectionError("The approved Git baseline commit is invalid.")
        whitespace_arguments.append(
            (("diff", "--check", head, "HEAD", "--"), "git-baseline-diff-check")
        )
    elif isinstance(baseline, dict) and baseline.get("source") == "filesystem":
        git_present, head_exists = _filesystem_git_state(root, baseline)
        if git_present and head_exists:
            empty_tree = _git_bytes(
                root,
                "hash-object",
                "-t",
                "tree",
                "--stdin",
                input_data=b"",
            )
            if empty_tree is None:
                raise GitInspectionError("Required unborn Git whitespace baseline failed.")
            whitespace_arguments.append(
                (
                    (
                        "diff",
                        "--check",
                        empty_tree.decode("ascii").strip(),
                        "HEAD",
                        "--",
                    ),
                    "git-unborn-head-diff-check",
                )
            )
    whitespace_arguments.extend(
        [
            (("diff", "--check"), "git-diff-check"),
            (("diff", "--cached", "--check"), "git-cached-diff-check"),
        ]
    )
    whitespace_checks = tuple(
        _git_whitespace_check(root, arguments, name)
        for arguments, name in whitespace_arguments
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
    if (
        starting_fingerprint["digest"] != ending_fingerprint["digest"]
        or starting_fingerprint.get("git_state_digest")
        != ending_fingerprint.get("git_state_digest")
    ):
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

    Verification is bound to both materialized files and the authoritative Git
    snapshot inspected by the gate. Tracked and untracked (non-ignored) paths
    are enumerated by Git, then read from the working tree; HEAD/index/diff
    state is recorded separately so post-gate Git transitions are detectable.
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
    aggregate_git_state = _aggregate_git_state_digest(
        git_state_digest,
        submodules,
    )
    return {
        "algorithm": "sha256",
        "format_version": 3,
        "digest": f"sha256:{digest.hexdigest()}",
        "content_digest": f"sha256:{digest.hexdigest()}",
        "git_state_digest": aggregate_git_state,
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
    if _validated_git_context(root, strict=False) is None:
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
        record: dict[str, Any] = {
            "path": encoded_name,
            "index_oid": index_oid,
            "head": b"<missing>",
            "status": b"<unavailable>",
            "files": 0,
            "content_digest": None,
            "git_state_digest": None,
        }
        resolved_submodule = _materialized_submodule_root(root, name)
        if resolved_submodule is None:
            record["state"] = b"uninitialized"
            submodules.append(record)
            continue
        head_result = _git_bytes(
            resolved_submodule,
            "rev-parse",
            "--verify",
            "HEAD",
        )
        status_result = _git_bytes(
            resolved_submodule,
            "status",
            "--porcelain=v1",
            "-z",
        )
        record["head"] = (
            head_result.strip() if head_result is not None else b"<missing>"
        )
        record["status"] = (
            status_result if status_result is not None else b"<unavailable>"
        )
        submodule_identity = os.path.normcase(str(resolved_submodule))
        if submodule_identity in ancestors:
            record["state"] = b"cycle"
        else:
            nested = _workspace_fingerprint(resolved_submodule, ancestors=ancestors)
            record["state"] = b"materialized-git"
            record["content_digest"] = nested["content_digest"].encode("ascii")
            record["git_state_digest"] = nested.get("git_state_digest")
            record["files"] = nested["files"]
        submodules.append(record)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix()), submodules


def _git_state_diagnostics(root: Path) -> tuple[str | None, str | None]:
    """Return Git snapshot evidence used by quality integrity checks."""

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


def _git_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("GIT_")
    }
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _aggregate_git_state_digest(
    root_git_state_digest: str | None,
    submodules: list[dict[str, Any]],
) -> str | None:
    if root_git_state_digest is None and not submodules:
        return None
    digest = hashlib.sha256()
    digest.update(b"anchorloop-git-state-tree-v1\0")
    _update_digest_value(
        digest,
        b"root",
        (root_git_state_digest or "<unavailable>").encode("ascii"),
    )
    for submodule in submodules:
        _update_digest_value(digest, b"submodule-path", submodule["path"])
        _update_digest_value(digest, b"submodule-index", submodule["index_oid"])
        _update_digest_value(digest, b"submodule-head", submodule["head"])
        _update_digest_value(digest, b"submodule-status", submodule["status"])
        nested = submodule.get("git_state_digest")
        _update_digest_value(
            digest,
            b"submodule-nested-state",
            (nested or "<unavailable>").encode("ascii"),
        )
    return f"sha256:{digest.hexdigest()}"


def _run_git(
    root: Path,
    *arguments: str,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            ["git", "--no-replace-objects", *arguments],
            cwd=root,
            capture_output=True,
            check=False,
            env=_git_environment(),
            input=input_data,
        )
    except OSError:
        return None


def _git_bytes(
    root: Path,
    *arguments: str,
    input_data: bytes | None = None,
) -> bytes | None:
    process = _run_git(root, *arguments, input_data=input_data)
    if process is None:
        return None
    if process.returncode != 0:
        return None
    return process.stdout


def _validated_git_context(
    root: Path,
    *,
    strict: bool,
) -> tuple[Path, str] | None:
    top_level = _git_bytes(root, "rev-parse", "--show-toplevel")
    if top_level is None:
        if strict:
            raise GitInspectionError(
                "Required Git inspection failed: git rev-parse --show-toplevel"
            )
        return None
    prefix = _git_bytes(root, "rev-parse", "--show-prefix")
    if prefix is None:
        raise GitInspectionError(
            "Required Git inspection failed: git rev-parse --show-prefix"
        )
    try:
        resolved_root = root.resolve(strict=True)
        discovered = Path(
            top_level.decode("utf-8", errors="surrogateescape").strip()
        ).resolve(strict=True)
        relative = resolved_root.relative_to(discovered)
    except (OSError, RuntimeError, ValueError) as error:
        raise GitInspectionError(
            "Git reported a repository outside the inspected project context."
        ) from error
    expected_prefix = "" if relative == Path(".") else relative.as_posix().strip("/")
    reported_prefix = prefix.decode(
        "utf-8",
        errors="surrogateescape",
    ).replace("\\", "/").strip().strip("/")
    if reported_prefix != expected_prefix:
        raise GitInspectionError(
            "Git reported a working-directory prefix that does not match the inspected project."
        )
    _reject_legacy_git_grafts(root)
    return discovered, reported_prefix


def _reject_legacy_git_grafts(root: Path) -> None:
    graft_path = _git_bytes(root, "rev-parse", "--git-path", "info/grafts")
    if graft_path is None:
        raise GitInspectionError("Required Git graft inspection failed.")
    decoded = graft_path.decode("utf-8", errors="surrogateescape").strip()
    if not decoded:
        raise GitInspectionError("Git reported an invalid legacy graft path.")
    candidate = Path(decoded)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        metadata = os.lstat(candidate)
    except FileNotFoundError:
        return
    except OSError as error:
        raise GitInspectionError("Legacy Git graft state cannot be inspected safely.") from error
    if (
        _is_windows_reparse_point(metadata)
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise GitInspectionError("Legacy Git graft state is unsafe.")
    try:
        contents = candidate.read_bytes()
    except OSError as error:
        raise GitInspectionError("Legacy Git graft state cannot be read safely.") from error
    if contents.strip():
        raise GitInspectionError(
            "Legacy Git grafts can rewrite commit ancestry and are not supported."
        )


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
    if _is_windows_reparse_point(metadata):
        raise GitInspectionError(
            f"Workspace fingerprint refuses Windows reparse point: {path}"
        )

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
    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = os.scandir(directory)
        except OSError as error:
            raise GitInspectionError(
                f"Workspace fingerprint cannot inspect directory safely: {directory}"
            ) from error
        with entries:
            for entry in entries:
                if entry.name in _SKIP_DIRECTORIES:
                    continue
                path = Path(entry.path)
                try:
                    metadata = os.lstat(path)
                except OSError as error:
                    raise GitInspectionError(
                        f"Workspace fingerprint cannot inspect path safely: {path}"
                    ) from error
                if _is_windows_reparse_point(metadata):
                    raise GitInspectionError(
                        f"Workspace fingerprint refuses Windows reparse point: {path}"
                    )
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                    files.append(path)
    return files


def _is_fingerprintable_path(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    if _is_windows_reparse_point(metadata):
        raise GitInspectionError(
            f"Workspace fingerprint refuses Windows reparse point: {path}"
        )
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


def _source_documents(
    root: Path,
    *,
    baseline: dict[str, Any] | None = None,
) -> list[tuple[str, str, bytes]]:
    """Return candidate source contents from every publishable Git snapshot.

    A worktree-only scan is insufficient: a safe unstaged file can hide a bad
    blob already committed to HEAD or staged in the index.  Git-backed tasks
    therefore scan baseline..HEAD blobs, index blobs, and current
    unstaged/untracked files independently.  Filesystem-backed tasks retain
    their materialized-tree semantics because no historical blob store exists.
    """

    if isinstance(baseline, dict) and baseline.get("source") == "filesystem":
        names = git_changed_path_names(root, baseline=baseline, strict=True)
        documents = _worktree_source_documents(root, names)
        git_present, head_exists = _filesystem_git_state(root, baseline)
        if git_present:
            documents.extend(
                _git_source_documents(
                    root,
                    baseline=None,
                    include_head_snapshot=head_exists,
                )
            )
        return documents

    if baseline is not None or _validated_git_context(root, strict=False) is not None:
        # Perform the full baseline/submodule validation before reading blobs.
        git_changed_path_names(root, baseline=baseline, strict=baseline is not None)
        return _git_source_documents(root, baseline=baseline)

    names = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if _is_supported_source_file(root, path)
    ]
    return _worktree_source_documents(root, names)


def _security_source_documents(
    root: Path,
    *,
    baseline: dict[str, Any] | None,
    documents: list[tuple[str, str, bytes]],
) -> list[tuple[str, str, bytes]]:
    """Add each new historical source blob once for the security scan only.

    Syntax and ownership checks intentionally retain their material-diff
    semantics. A credential is different: even a reverted blob is reachable
    from the branch and would be pushed, so security must inspect the complete
    approved-baseline-to-HEAD history.
    """

    historical = _git_history_source_documents(
        root,
        baseline=baseline,
        budget=_HistoryScanBudget(),
    )
    if not historical:
        return documents
    known_contents = {
        hashlib.sha256(content).digest()
        for _, _, content in documents
    }
    combined = list(documents)
    for document in historical:
        content_digest = hashlib.sha256(document[2]).digest()
        if content_digest in known_contents:
            continue
        known_contents.add(content_digest)
        combined.append(document)
    return combined


def _git_history_source_documents(
    root: Path,
    *,
    baseline: dict[str, Any] | None,
    display_prefix: str = "",
    ancestors: frozenset[str] = frozenset(),
    budget: _HistoryScanBudget,
) -> list[tuple[str, str, bytes]]:
    """Return source blobs newly reachable after an approved Git baseline."""

    if not isinstance(baseline, dict):
        return []
    source = baseline.get("source")
    if source == "filesystem":
        # An unborn repository has no commit object to bind the approval to.
        # Once it has a HEAD, inspect all reachable objects rather than letting
        # a first-commit secret disappear behind a later committed revert.
        git_present, head_exists = _filesystem_git_state(root, baseline)
        if not git_present or not head_exists:
            return []
        context = _validated_git_context(root, strict=True)
        if context is None:
            raise GitInspectionError("Required Git history context is unavailable.")
        head = _git_bytes(root, "rev-parse", "--verify", "HEAD")
        if head is None:
            raise GitInspectionError("Required Git history HEAD is unavailable.")
        return _git_full_history_source_documents(
            root,
            commit=head.decode("ascii", errors="strict").strip(),
            display_prefix=display_prefix,
            ancestors=ancestors,
            budget=budget,
        )
    if source != "git":
        return []

    identity = os.path.normcase(str(root.resolve()))
    if identity in ancestors:
        raise GitInspectionError("Git submodule cycle detected during history inspection.")
    context = _validated_git_context(root, strict=True)
    if context is None:
        raise GitInspectionError("Required Git history context is unavailable.")
    baseline_head = baseline.get("head")
    if not isinstance(baseline_head, str) or re.fullmatch(
        r"(?:[0-9a-f]{40}|[0-9a-f]{64})", baseline_head
    ) is None:
        raise GitInspectionError("The approved Git baseline commit is invalid.")
    expected_prefix = baseline.get("project_prefix")
    if not isinstance(expected_prefix, str) or context[1] != expected_prefix:
        raise GitInspectionError(
            "The approved Git baseline belongs to a different project path."
        )
    current_head = _git_bytes(root, "rev-parse", "--verify", "HEAD")
    if current_head is None:
        raise GitInspectionError("Required Git history HEAD is unavailable.")
    current_head_text = current_head.decode("ascii", errors="strict").strip()
    if _git_bytes(root, "merge-base", "--is-ancestor", baseline_head, current_head_text) is None:
        raise GitInspectionError("The approved Git baseline is no longer an ancestor of HEAD.")
    submodules = baseline.get("submodules", {})
    if not isinstance(submodules, dict):
        raise GitInspectionError("The approved Git submodule baseline is invalid.")
    approved_gitlinks = baseline.get("submodule_oids", {})
    if (
        not isinstance(approved_gitlinks, dict)
        or set(approved_gitlinks) != set(submodules)
        or not all(
            isinstance(object_id, str)
            and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", object_id)
            is not None
            for object_id in approved_gitlinks.values()
        )
    ):
        raise GitInspectionError("The approved Git submodule OIDs are invalid.")
    current_gitlinks = _gitlink_paths(root, treeish=current_head_text)
    if set(current_gitlinks) != set(submodules):
        raise GitInspectionError(
            "The approved Git submodule set changed in parent history."
        )

    allowed_gitlinks: dict[str, str] = {}
    materialized_submodules: dict[str, tuple[Path, dict[str, Any]]] = {}
    for name, nested_baseline in sorted(submodules.items()):
        approved_gitlink = approved_gitlinks[name]
        current_gitlink = current_gitlinks[name]
        if nested_baseline is None:
            # An unmaterialized child has no baseline repository we can scan.
            # It must therefore remain pinned to its approved gitlink; accepting
            # a parent-tree advance would let a secret be introduced and reverted
            # entirely inside the unavailable child history.
            if current_gitlink != approved_gitlink:
                raise GitInspectionError(
                    "Git history contains an unmaterialized submodule transition "
                    f"that cannot be inspected safely: {name}"
                )
            continue
        if not isinstance(nested_baseline, dict):
            raise GitInspectionError("The approved Git submodule baseline is invalid.")
        nested_root = _materialized_submodule_root(root, name)
        if nested_root is None:
            raise GitInspectionError(
                f"Git submodule baseline is unavailable after approval: {name}"
            )
        nested_head = _git_bytes(nested_root, "rev-parse", "--verify", "HEAD")
        if (
            nested_head is None
            or (
                current_gitlink != approved_gitlink
                and nested_head.decode("ascii", errors="strict").strip()
                != current_gitlink
            )
        ):
            raise GitInspectionError(
                f"Git submodule materialized commit does not match parent HEAD: {name}"
            )
        allowed_gitlinks[name] = current_gitlink
        materialized_submodules[name] = (nested_root, nested_baseline)

    documents = _git_history_blob_documents(
        root,
        revision=f"{baseline_head}..{current_head_text}",
        repository_prefix=context[1],
        display_prefix=display_prefix,
        budget=budget,
        allowed_gitlinks=allowed_gitlinks,
    )
    for name, (nested_root, nested_baseline) in sorted(materialized_submodules.items()):
        documents.extend(
            _git_history_source_documents(
                nested_root,
                baseline=nested_baseline,
                display_prefix=f"{display_prefix}{name}/",
                ancestors=ancestors | {identity},
                budget=budget,
            )
        )
    return documents


def _git_full_history_source_documents(
    root: Path,
    *,
    commit: str,
    display_prefix: str,
    ancestors: frozenset[str],
    budget: _HistoryScanBudget,
) -> list[tuple[str, str, bytes]]:
    """Scan a complete Git history when approval predates the first commit."""

    identity = os.path.normcase(str(root.resolve()))
    if identity in ancestors:
        raise GitInspectionError("Git submodule cycle detected during history inspection.")
    context = _validated_git_context(root, strict=True)
    if context is None or _git_bytes(root, "cat-file", "-e", f"{commit}^{{commit}}") is None:
        raise GitInspectionError("Required Git history commit is unavailable.")
    documents = _git_history_blob_documents(
        root,
        revision=commit,
        repository_prefix=context[1],
        display_prefix=display_prefix,
        budget=budget,
        allowed_gitlinks=_gitlink_paths(root, treeish=commit),
    )
    for name, nested_commit in sorted(_gitlink_paths(root, treeish=commit).items()):
        nested_root = _materialized_submodule_root(root, name)
        if nested_root is None:
            raise GitInspectionError(
                f"Git history submodule is not materialized: {display_prefix}{name}"
            )
        nested_head = _git_bytes(nested_root, "rev-parse", "--verify", "HEAD")
        if (
            nested_head is None
            or nested_head.decode("ascii", errors="strict").strip() != nested_commit
        ):
            raise GitInspectionError(
                f"Git history submodule index and materialized commit disagree: "
                f"{display_prefix}{name}"
            )
        documents.extend(
            _git_full_history_source_documents(
                nested_root,
                commit=nested_commit,
                display_prefix=f"{display_prefix}{name}/",
                ancestors=ancestors | {identity},
                budget=budget,
            )
        )
    return documents


def _git_history_blob_documents(
    root: Path,
    *,
    revision: str,
    repository_prefix: str,
    display_prefix: str,
    budget: _HistoryScanBudget,
    allowed_gitlinks: dict[str, str],
) -> list[tuple[str, str, bytes]]:
    """Read bounded, supported source blobs from a Git object revision set."""

    object_paths = _git_history_object_paths(
        root,
        revision=revision,
        repository_prefix=repository_prefix,
        budget=budget,
        allowed_gitlinks=allowed_gitlinks,
    )
    if not object_paths:
        return []
    object_ids = sorted(object_paths)
    checked = _git_bytes(
        root,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        input_data=b"\n".join(object_ids) + b"\n",
    )
    if checked is None:
        raise GitInspectionError("Required Git history object inspection failed.")
    records = checked.splitlines()
    if len(records) != len(object_ids):
        raise GitInspectionError("Git history object inspection returned incomplete records.")

    blobs: list[tuple[bytes, int, str]] = []
    for object_id, record in zip(object_ids, records, strict=True):
        fields = record.split(b" ", 2)
        if len(fields) != 3 or fields[0] != object_id:
            raise GitInspectionError("Git history object inspection returned a malformed record.")
        object_type = fields[1]
        if object_type == b"missing":
            raise GitInspectionError("A required Git history object is unavailable.")
        if object_type != b"blob":
            continue
        try:
            size = int(fields[2])
        except ValueError as error:
            raise GitInspectionError(
                "Git history object inspection returned an invalid size."
            ) from error
        if size < 0 or size > _HISTORY_SCAN_MAX_BYTES - budget.bytes:
            raise GitInspectionError(
                f"Git history blob byte limit exceeded ({_HISTORY_SCAN_MAX_BYTES})."
            )
        budget.bytes += size
        blobs.append((object_id, size, object_paths[object_id]))
    if not blobs:
        return []

    content_output = _git_bytes(
        root,
        "cat-file",
        "--batch",
        input_data=b"\n".join(object_id for object_id, _, _ in blobs) + b"\n",
    )
    if content_output is None:
        raise GitInspectionError("Required Git history blob read failed.")
    position = 0
    documents: list[tuple[str, str, bytes]] = []
    for object_id, size, name in blobs:
        header_end = content_output.find(b"\n", position)
        expected_header = object_id + b" blob " + str(size).encode("ascii")
        if header_end < 0 or content_output[position:header_end] != expected_header:
            raise GitInspectionError("Git history blob read returned a malformed record.")
        position = header_end + 1
        content_end = position + size
        content = content_output[position:content_end]
        if len(content) != size or content_output[content_end:content_end + 1] != b"\n":
            raise GitInspectionError("Git history blob read returned incomplete content.")
        position = content_end + 1
        documents.append((f"{display_prefix}{name}", "history", content))
    if position != len(content_output):
        raise GitInspectionError("Git history blob read returned unexpected trailing data.")
    return documents


def _git_history_object_paths(
    root: Path,
    *,
    revision: str,
    repository_prefix: str,
    budget: _HistoryScanBudget,
    allowed_gitlinks: dict[str, str],
) -> dict[bytes, str]:
    """Map every historical source-path transition to its new blob.

    ``rev-list --objects`` emits at most one arbitrary path hint for a blob.
    That is unsafe when one blob is reachable at both a supported and an
    unsupported path. Enumerating each reachable commit's raw tree transition
    preserves all paths, including merged side-branch commits.
    """

    object_paths: dict[bytes, str] = {}
    for commit in _git_history_commit_ids(root, revision=revision, budget=budget):
        _git_history_commit_object_paths(
            root,
            commit=commit,
            repository_prefix=repository_prefix,
            object_paths=object_paths,
            budget=budget,
            allowed_gitlinks=allowed_gitlinks,
        )
    return object_paths


def _git_history_commit_ids(
    root: Path,
    *,
    revision: str,
    budget: _HistoryScanBudget,
) -> list[str]:
    commits: list[str] = []

    def collect(record: bytes) -> None:
        if _GIT_OBJECT_ID.fullmatch(record) is None:
            raise GitInspectionError(
                "Git history enumeration returned a malformed commit ID."
            )
        if len(commits) >= _HISTORY_SCAN_MAX_COMMITS:
            raise GitInspectionError(
                f"Git history commit limit exceeded ({_HISTORY_SCAN_MAX_COMMITS})."
            )
        _consume_history_object_budget(budget)
        commits.append(record.decode("ascii"))

    _stream_git_line_records(
        root,
        ("rev-list", "--full-history", revision, "--", "."),
        collect,
        operation="history enumeration",
    )
    return commits


def _git_history_commit_object_paths(
    root: Path,
    *,
    commit: str,
    repository_prefix: str,
    object_paths: dict[bytes, str],
    budget: _HistoryScanBudget,
    allowed_gitlinks: dict[str, str],
) -> None:
    pending_object: bytes | None = None
    pending_gitlink = False

    def collect(record: bytes) -> None:
        nonlocal pending_gitlink, pending_object
        if pending_object is None:
            fields = record.split()
            if (
                len(fields) != 5
                or not fields[0].startswith(b":")
                or _GIT_OBJECT_ID.fullmatch(fields[3]) is None
                or fields[4] not in {b"A", b"M", b"T"}
            ):
                raise GitInspectionError(
                    "Git history enumeration returned a malformed tree transition."
                )
            _consume_history_object_budget(budget)
            pending_object = fields[3]
            pending_gitlink = fields[1] == b"160000"
            return
        if pending_gitlink:
            name = _git_history_relative_name(
                record,
                repository_prefix=repository_prefix,
            )
            expected_gitlink = allowed_gitlinks.get(name) if name is not None else None
            if expected_gitlink != pending_object.decode("ascii"):
                raise GitInspectionError(
                    "Git history contains a submodule transition that cannot "
                    "be inspected safely."
                )
            pending_gitlink = False
            pending_object = None
            return
        name = _git_history_source_name(
            record,
            repository_prefix=repository_prefix,
        )
        if name is not None:
            existing_name = object_paths.get(pending_object)
            if existing_name is None or name < existing_name:
                object_paths[pending_object] = name
        pending_object = None

    _stream_git_nul_records(
        root,
        (
            "diff-tree",
            "--root",
            "-m",
            "-r",
            "--no-commit-id",
            "--no-renames",
            "--diff-filter=AMT",
            "--raw",
            "-z",
            commit,
            "--",
            ".",
        ),
        collect,
        operation="history tree enumeration",
    )
    if pending_object is not None or pending_gitlink:
        raise GitInspectionError(
            "Git history enumeration returned an incomplete tree transition."
        )


def _consume_history_object_budget(budget: _HistoryScanBudget) -> None:
    budget.objects += 1
    if budget.objects > _HISTORY_SCAN_MAX_OBJECTS:
        raise GitInspectionError(
            f"Git history object limit exceeded ({_HISTORY_SCAN_MAX_OBJECTS})."
        )


def _stream_git_line_records(
    root: Path,
    arguments: tuple[str, ...],
    on_record: Any,
    *,
    operation: str,
) -> None:
    """Call Git and feed newline-delimited records without unbounded buffering."""

    _stream_git_records(
        root,
        arguments,
        on_record,
        delimiter=b"\n",
        operation=operation,
    )


def _stream_git_nul_records(
    root: Path,
    arguments: tuple[str, ...],
    on_record: Any,
    *,
    operation: str,
) -> None:
    """Call Git and feed NUL-delimited records without unbounded buffering."""

    _stream_git_records(
        root,
        arguments,
        on_record,
        delimiter=b"\0",
        operation=operation,
    )


def _stream_git_records(
    root: Path,
    arguments: tuple[str, ...],
    on_record: Any,
    *,
    delimiter: bytes,
    operation: str,
) -> None:
    """Call Git and feed delimited records without unbounded buffering."""

    try:
        process = subprocess.Popen(
            ["git", "--no-replace-objects", *arguments],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_git_environment(),
        )
    except OSError as error:
        raise GitInspectionError(f"Required Git {operation} failed.") from error
    stream = process.stdout
    if stream is None:
        process.terminate()
        process.wait()
        raise GitInspectionError(f"Required Git {operation} has no output stream.")
    buffered = b""
    try:
        while chunk := stream.read(64 * 1024):
            buffered += chunk
            if len(buffered) > 1024 * 1024:
                raise GitInspectionError(
                    f"Git {operation} returned an oversized record."
                )
            records = buffered.split(delimiter)
            buffered = records.pop()
            for record in records:
                on_record(record)
        if buffered:
            raise GitInspectionError(
                f"Git {operation} returned an unterminated record."
            )
        if process.wait() != 0:
            raise GitInspectionError(f"Required Git {operation} failed.")
    except OSError as error:
        raise GitInspectionError(f"Required Git {operation} failed.") from error
    finally:
        stream.close()
        if process.poll() is None:
            process.terminate()
            process.wait()


def _git_history_source_name(
    encoded_name: bytes,
    *,
    repository_prefix: str,
) -> str | None:
    name = _git_history_relative_name(
        encoded_name,
        repository_prefix=repository_prefix,
    )
    if name is None:
        return None
    if name == ".anchor" or name.startswith(".anchor/"):
        return None
    if os.name == "nt" and "\\" in name:
        raise GitInspectionError(
            "Git history contains a path that cannot be inspected safely on Windows."
        )
    return name if _is_supported_source_name(name) else None


def _git_history_relative_name(
    encoded_name: bytes,
    *,
    repository_prefix: str,
) -> str | None:
    """Return a validated Git path relative to the inspected project root."""

    prefix = repository_prefix.encode("utf-8", errors="surrogateescape").strip(b"/")
    if prefix:
        expected_prefix = prefix + b"/"
        if not encoded_name.startswith(expected_prefix):
            return None
        encoded_name = encoded_name[len(expected_prefix):]
    name = encoded_name.decode("utf-8", errors="surrogateescape")
    while name.startswith("./"):
        name = name[2:]
    if (
        not name
        or name.startswith("/")
        or ".." in name.split("/")
    ):
        raise GitInspectionError("Git history enumeration returned an unsafe path.")
    return name


def _git_source_documents(
    root: Path,
    *,
    baseline: dict[str, Any] | None,
    display_prefix: str = "",
    include_head_snapshot: bool = False,
) -> list[tuple[str, str, bytes]]:
    context = _validated_git_context(root, strict=baseline is not None)
    if context is None:
        return []
    repository_prefix = context[1]
    candidates: list[tuple[tuple[str, ...], str, str | None]] = [
        (
            (
                "diff",
                "--cached",
                "--relative",
                "--no-renames",
                "--diff-filter=ACMRTUXB",
                "--name-only",
                "-z",
                "--",
            ),
            "index",
            "index",
        ),
        (
            (
                "diff",
                "--relative",
                "--no-renames",
                "--diff-filter=ACMRTUXB",
                "--name-only",
                "-z",
                "--",
            ),
            "worktree",
            None,
        ),
        (
            ("ls-files", "--others", "--exclude-standard", "-z", "--"),
            "worktree",
            None,
        ),
    ]
    if baseline is not None:
        head = baseline.get("head")
        if not isinstance(head, str) or re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head
        ) is None:
            raise GitInspectionError("The approved Git baseline commit is invalid.")
        candidates.insert(
            0,
            (
                (
                    "diff",
                    "--relative",
                    "--no-renames",
                    "--diff-filter=ACMRTUXB",
                    "--name-only",
                    "-z",
                    head,
                    "HEAD",
                    "--",
                ),
                "HEAD",
                "HEAD",
            ),
        )

    documents: list[tuple[str, str, bytes]] = []
    seen: set[tuple[str, bytes]] = set()
    for arguments, snapshot, git_object in candidates:
        output = _git_bytes(root, *arguments)
        if output is None:
            raise GitInspectionError(
                "Required Git source inspection failed: git " + " ".join(arguments)
            )
        for name in _normalized_git_names(output):
            if not _is_supported_source_name(name):
                continue
            display_name = f"{display_prefix}{name}"
            if git_object is None:
                path = root / name
                if not _is_regular_file(path):
                    raise GitInspectionError(
                        f"Required worktree source disappeared during inspection: {display_name}"
                    )
                try:
                    content = path.read_bytes()
                except OSError as error:
                    raise GitInspectionError(
                        f"Required worktree source is unreadable: {display_name}"
                    ) from error
            else:
                repository_name = (
                    f"{repository_prefix}/{name}" if repository_prefix else name
                )
                object_name = (
                    f"HEAD:{repository_name}"
                    if git_object == "HEAD"
                    else f":0:{repository_name}"
                )
                content = _git_bytes(root, "cat-file", "blob", object_name)
                if content is None:
                    raise GitInspectionError(
                        f"Required Git {snapshot} blob is unreadable: {display_name}"
                    )
            dedupe_key = (display_name, hashlib.sha256(content).digest())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            documents.append((display_name, snapshot, content))

    if isinstance(baseline, dict):
        submodules = baseline.get("submodules", {})
        if not isinstance(submodules, dict):
            raise GitInspectionError("The approved Git submodule baseline is invalid.")
        for name, nested_baseline in sorted(submodules.items()):
            if not isinstance(nested_baseline, dict):
                continue
            nested_root = _materialized_submodule_root(root, name)
            if nested_root is None:
                raise GitInspectionError(
                    f"Git submodule baseline is unavailable after approval: {name}"
                )
            documents.extend(
                _git_source_documents(
                    nested_root,
                    baseline=nested_baseline,
                    display_prefix=f"{display_prefix}{name}/",
                )
            )
    elif baseline is None:
        if include_head_snapshot:
            head = _git_bytes(root, "rev-parse", "--verify", "HEAD")
            if head is None:
                raise GitInspectionError("Required Git HEAD tree is unavailable.")
            documents.extend(
                _git_tree_source_documents(
                    root,
                    commit=head.decode("ascii").strip(),
                    display_prefix=display_prefix,
                    ancestors=frozenset(),
                )
            )
        for name, oid in sorted(_gitlink_paths(root).items()):
            nested_root = _materialized_submodule_root(root, name)
            if nested_root is None:
                raise GitInspectionError(
                    f"Git transition submodule is not materialized: {name}"
                )
            documents.extend(
                _git_tree_source_documents(
                    nested_root,
                    commit=oid,
                    display_prefix=f"{display_prefix}{name}/",
                    ancestors=frozenset(),
                )
            )
            documents.extend(
                _git_source_documents(
                    nested_root,
                    baseline=None,
                    display_prefix=f"{display_prefix}{name}/",
                    include_head_snapshot=True,
                )
            )
    return documents


def _git_tree_source_documents(
    root: Path,
    *,
    commit: str,
    display_prefix: str,
    ancestors: frozenset[str],
) -> list[tuple[str, str, bytes]]:
    identity = os.path.normcase(str(root.resolve()))
    if identity in ancestors:
        raise GitInspectionError("Git submodule cycle detected during source inspection.")
    context = _validated_git_context(root, strict=True)
    if context is None or _git_bytes(
        root,
        "cat-file",
        "-e",
        f"{commit}^{{commit}}",
    ) is None:
        raise GitInspectionError("Required Git tree commit is unavailable.")
    output = _git_bytes(
        root,
        "ls-tree",
        "-r",
        "--name-only",
        "-z",
        commit,
        "--",
        ".",
    )
    if output is None:
        raise GitInspectionError("Required Git tree source enumeration failed.")
    repository_prefix = context[1]
    documents: list[tuple[str, str, bytes]] = []
    for name in _normalized_git_names(output):
        if not _is_supported_source_name(name):
            continue
        repository_name = f"{repository_prefix}/{name}" if repository_prefix else name
        content = _git_bytes(root, "cat-file", "blob", f"{commit}:{repository_name}")
        if content is None:
            raise GitInspectionError(
                f"Required Git tree blob is unreadable: {display_prefix}{name}"
            )
        documents.append((f"{display_prefix}{name}", "HEAD", content))
    for name, oid in sorted(_gitlink_paths(root, treeish=commit).items()):
        nested_root = _materialized_submodule_root(root, name)
        if nested_root is None:
            raise GitInspectionError(
                f"Git tree submodule is not materialized: {display_prefix}{name}"
            )
        documents.extend(
            _git_tree_source_documents(
                nested_root,
                commit=oid,
                display_prefix=f"{display_prefix}{name}/",
                ancestors=ancestors | {identity},
            )
        )
    return documents


def _git_tree_path_names(
    root: Path,
    *,
    commit: str,
    display_prefix: str,
    ancestors: frozenset[str],
) -> list[str]:
    identity = os.path.normcase(str(root.resolve()))
    if identity in ancestors:
        raise GitInspectionError("Git submodule cycle detected during path inspection.")
    if _validated_git_context(root, strict=True) is None or _git_bytes(
        root,
        "cat-file",
        "-e",
        f"{commit}^{{commit}}",
    ) is None:
        raise GitInspectionError("Required Git transition tree is unavailable.")
    output = _git_bytes(
        root,
        "ls-tree",
        "-r",
        "--name-only",
        "-z",
        commit,
        "--",
        ".",
    )
    if output is None:
        raise GitInspectionError("Required Git transition path enumeration failed.")
    names = [f"{display_prefix}{name}" for name in _normalized_git_names(output)]
    for name, oid in sorted(_gitlink_paths(root, treeish=commit).items()):
        nested_root = _materialized_submodule_root(root, name)
        if nested_root is None:
            raise GitInspectionError(
                f"Git transition submodule is not materialized: {display_prefix}{name}"
            )
        names.extend(
            _git_tree_path_names(
                nested_root,
                commit=oid,
                display_prefix=f"{display_prefix}{name}/",
                ancestors=ancestors | {identity},
            )
        )
    return names


def _git_index_submodule_path_names(
    root: Path,
    *,
    display_prefix: str,
    ancestors: frozenset[str],
) -> list[str]:
    identity = os.path.normcase(str(root.resolve()))
    if identity in ancestors:
        raise GitInspectionError("Git submodule cycle detected during index inspection.")
    names: list[str] = []
    for name, oid in sorted(_gitlink_paths(root).items()):
        nested_root = _materialized_submodule_root(root, name)
        full_prefix = f"{display_prefix}{name}/"
        if nested_root is None:
            raise GitInspectionError(
                f"Git transition submodule is not materialized: {display_prefix}{name}"
            )
        names.extend(
            _git_tree_path_names(
                nested_root,
                commit=oid,
                display_prefix=full_prefix,
                ancestors=ancestors | {identity},
            )
        )
        names.extend(
            f"{full_prefix}{path}"
            for path in git_changed_path_names(
                nested_root,
                baseline=None,
                strict=True,
            )
        )
        names.extend(
            _git_index_submodule_path_names(
                nested_root,
                display_prefix=full_prefix,
                ancestors=ancestors | {identity},
            )
        )
    return names


def _normalized_git_names(output: bytes) -> list[str]:
    names: list[str] = []
    for encoded_name in output.split(b"\0"):
        if not encoded_name:
            continue
        name = encoded_name.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        while name.startswith("./"):
            name = name[2:]
        parsed = Path(name)
        if (
            not name
            or name == ".anchor"
            or name.startswith(".anchor/")
            or parsed.is_absolute()
            or bool(parsed.drive)
            or bool(parsed.root)
            or ".." in parsed.parts
        ):
            continue
        names.append(name)
    return names


def _worktree_source_documents(
    root: Path,
    names: list[str],
) -> list[tuple[str, str, bytes]]:
    documents: list[tuple[str, str, bytes]] = []
    for name in sorted(set(names)):
        path = root / name
        if not _is_supported_source_file(root, path):
            continue
        try:
            documents.append((name, "worktree", path.read_bytes()))
        except OSError as error:
            raise GitInspectionError(
                f"Required worktree source is unreadable: {name}"
            ) from error
    return documents


def _is_supported_source_name(name: str) -> bool:
    path = Path(name)
    return (
        not any(part in _SKIP_DIRECTORIES for part in path.parts)
        and (path.suffix.lower() in _TEXT_SUFFIXES or path.name.startswith(".env"))
    )


def task_change_baseline(root: Path) -> dict[str, Any]:
    """Capture the material task baseline used by actual-diff gates.

    A Git commit is the compact, authoritative baseline when HEAD exists. An
    unborn or non-Git workspace falls back to the same materialized-file
    semantics used by workspace fingerprints, represented as per-path digests
    so later gates can still identify risky paths.
    """

    try:
        resolved_root = root.resolve(strict=True)
    except OSError as error:
        raise GitInspectionError(
            "Required task baseline root inspection failed."
        ) from error
    return _task_change_baseline(resolved_root, ancestors=frozenset())


def _task_change_baseline(
    root: Path,
    *,
    ancestors: frozenset[str],
) -> dict[str, Any]:
    identity = os.path.normcase(str(root.resolve()))
    if identity in ancestors:
        raise GitInspectionError("Git submodule cycle detected while capturing the task baseline.")

    git_context = _validated_git_context(root, strict=False)
    if git_context is not None:
        head = _git_bytes(root, "rev-parse", "--verify", "HEAD")
        prefix = git_context[1]
        if head:
            head_text = head.decode("ascii", errors="strict").strip()
            return _git_change_baseline_at_commit(
                root,
                head=head_text,
                project_prefix=prefix,
                ancestors=ancestors | {identity},
            )
        baseline = _filesystem_change_baseline(root)
        baseline["git_context"] = "unborn"
        baseline["git_unborn"] = True
        baseline["project_prefix"] = prefix
        return baseline
    try:
        baseline = _filesystem_change_baseline(root)
        baseline["git_context"] = "none"
        return baseline
    except OSError as error:
        raise GitInspectionError(
            f"Required filesystem baseline inspection failed: {error}"
        ) from error


def _filesystem_change_baseline(root: Path) -> dict[str, Any]:
    entries: dict[str, str] = {}
    total_bytes = 0
    for path in sorted(
        _strict_task_baseline_files(root),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        digest, measured_bytes = _strict_task_file_digest(
            root,
            path,
            remaining_bytes=_TASK_BASELINE_MAX_BYTES - total_bytes,
        )
        total_bytes += measured_bytes
        entries[path.relative_to(root).as_posix()] = digest
    return {
        "source": "filesystem",
        "format_version": 1,
        "entries": entries,
        "entry_count": len(entries),
        "total_bytes": total_bytes,
    }


def _strict_task_baseline_files(root: Path) -> list[Path]:
    """Enumerate task-baseline files without the fingerprint's soft failures."""

    files: list[Path] = []
    pending = [root]
    inspected_entries = 0
    while pending:
        directory = pending.pop()
        # pathlib.rglob intentionally suppresses selected scandir errors on
        # current Python releases. A security baseline must propagate them.
        with os.scandir(directory) as entries:
            for entry in entries:
                inspected_entries += 1
                if inspected_entries > _TASK_BASELINE_MAX_ENTRIES:
                    raise OSError(
                        "Task baseline entry limit exceeded "
                        f"({_TASK_BASELINE_MAX_ENTRIES})."
                    )
                if entry.name in _SKIP_DIRECTORIES:
                    continue
                path = Path(entry.path)
                metadata = os.lstat(path)
                if _is_windows_reparse_point(metadata):
                    raise OSError(
                        f"Task baseline refuses Windows reparse point: {path}"
                    )
                if stat.S_ISLNK(metadata.st_mode):
                    files.append(path)
                elif stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(metadata.st_mode):
                    files.append(path)
    return files


def _is_windows_reparse_point(metadata: os.stat_result) -> bool:
    return os.name == "nt" and bool(
        getattr(metadata, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT
    )


def _strict_task_file_digest(
    root: Path,
    path: Path,
    *,
    remaining_bytes: int,
) -> tuple[str, int]:
    """Digest one baseline file, raising on every inspection/read failure."""

    digest = hashlib.sha256()
    digest.update(b"anchorloop-task-file-v1\0")
    relative_path = path.relative_to(root).as_posix().encode(
        "utf-8",
        errors="surrogateescape",
    )
    metadata = os.lstat(path)
    if _is_windows_reparse_point(metadata):
        raise OSError(f"Task baseline refuses Windows reparse point: {path}")
    mode = str(stat.S_IMODE(metadata.st_mode)).encode("ascii")
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path).encode("utf-8", errors="surrogateescape")
        if len(target) > remaining_bytes:
            raise OSError(
                f"Task baseline byte limit exceeded ({_TASK_BASELINE_MAX_BYTES})."
            )
        _update_digest_value(digest, b"entry", b"symlink")
        _update_digest_value(digest, b"path", relative_path)
        _update_digest_value(digest, b"mode", mode)
        _update_digest_value(digest, b"target", target)
        return f"sha256:{digest.hexdigest()}", len(target)
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(f"Task baseline path changed type while scanning: {path}")

    file_digest = hashlib.sha256()
    size = 0
    if metadata.st_size > remaining_bytes:
        raise OSError(
            f"Task baseline byte limit exceeded ({_TASK_BASELINE_MAX_BYTES})."
        )
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (metadata.st_dev, metadata.st_ino):
            raise OSError("task baseline target changed while it was opened")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            while chunk := stream.read(
                min(1024 * 1024, max(1, remaining_bytes - size + 1))
            ):
                size += len(chunk)
                if size > remaining_bytes:
                    raise OSError(
                        "Task baseline byte limit exceeded "
                        f"({_TASK_BASELINE_MAX_BYTES})."
                    )
                file_digest.update(chunk)
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    _update_digest_value(digest, b"entry", b"file")
    _update_digest_value(digest, b"path", relative_path)
    _update_digest_value(digest, b"mode", mode)
    _update_digest_value(digest, b"size", str(size).encode("ascii"))
    _update_digest_value(digest, b"content-sha256", file_digest.digest())
    return f"sha256:{digest.hexdigest()}", size


def _gitlink_paths(root: Path, *, treeish: str | None = None) -> dict[str, str]:
    staged = (
        _git_bytes(root, "ls-files", "--stage", "-z", "--")
        if treeish is None
        else _git_bytes(root, "ls-tree", "-r", "-z", treeish, "--", ".")
    )
    if staged is None:
        raise GitInspectionError("Required Git submodule inspection failed: git ls-files")
    gitlinks: dict[str, str] = {}
    for record in staged.split(b"\0"):
        if not record or b"\t" not in record:
            continue
        metadata, encoded_name = record.split(b"\t", 1)
        fields = metadata.split()
        if fields[:1] != [b"160000"]:
            continue
        oid_index = 1 if treeish is None else 2
        if len(fields) <= oid_index:
            raise GitInspectionError("Required Git submodule record is malformed.")
        name = encoded_name.decode(
            "utf-8",
            errors="surrogateescape",
        ).replace("\\", "/")
        while name.startswith("./"):
            name = name[2:]
        gitlinks[name] = fields[oid_index].decode("ascii", errors="strict")
    return gitlinks


def _materialized_submodule_root(root: Path, name: str) -> Path | None:
    candidate = root / Path(name)
    try:
        metadata = os.lstat(candidate)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise GitInspectionError(
            f"Git submodule path cannot be inspected safely: {name}"
        ) from error
    if (
        _is_windows_reparse_point(metadata)
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise GitInspectionError(f"Git submodule path is unsafe: {name}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError) as error:
        raise GitInspectionError(f"Git submodule path escapes the project: {name}") from error
    nested_git_root = _git_bytes(candidate, "rev-parse", "--show-toplevel")
    if nested_git_root is None:
        return None
    try:
        discovered = Path(
            nested_git_root.decode("utf-8", errors="surrogateescape").strip()
        ).resolve(strict=True)
    except OSError as error:
        raise GitInspectionError(f"Git submodule root is unavailable: {name}") from error
    if os.path.normcase(str(discovered)) != os.path.normcase(str(resolved)):
        # An empty/uninitialized gitlink directory inherits the parent repo
        # when Git searches upward; it is not a materialized submodule.
        return None
    return resolved


def _git_change_baseline_at_commit(
    root: Path,
    *,
    head: str,
    project_prefix: str,
    ancestors: frozenset[str],
) -> dict[str, Any]:
    gitlinks = _gitlink_paths(root, treeish=head)
    baselines: dict[str, dict[str, Any] | None] = {}
    for name, oid in sorted(gitlinks.items()):
        nested_root = _materialized_submodule_root(root, name)
        if nested_root is None:
            baselines[name] = None
            continue
        identity = os.path.normcase(str(nested_root.resolve()))
        if identity in ancestors:
            raise GitInspectionError(
                "Git submodule cycle detected while capturing the task baseline."
            )
        nested_context = _validated_git_context(nested_root, strict=True)
        if nested_context is None or _git_bytes(
            nested_root,
            "cat-file",
            "-e",
            f"{oid}^{{commit}}",
        ) is None:
            raise GitInspectionError(
                f"Approved Git submodule commit is unavailable: {name}"
            )
        baselines[name] = _git_change_baseline_at_commit(
            nested_root,
            head=oid,
            project_prefix=nested_context[1],
            ancestors=ancestors | {identity},
        )
    return {
        "source": "git",
        "format_version": 1,
        "head": head,
        "project_prefix": project_prefix,
        "submodule_oids": gitlinks,
        "submodules": baselines,
    }


def git_changed_path_names(
    root: Path,
    *,
    baseline: dict[str, Any] | None = None,
    strict: bool = False,
) -> list[str]:
    """Return normalized changed paths, including committed and deleted files.

    With a task baseline, Git repositories include ``baseline..HEAD`` plus
    staged, unstaged, and untracked paths. Filesystem baselines compare the
    current materialized per-path digests instead.
    """

    if baseline is not None and baseline.get("source") == "filesystem":
        return _filesystem_changed_path_names(root, baseline, strict=strict)

    git_context = _validated_git_context(root, strict=strict)
    if git_context is None:
        return []
    commands: tuple[tuple[str, ...], ...] = (
        ("diff", "--relative", "--no-renames", "--name-only", "-z", "--"),
        ("diff", "--cached", "--relative", "--no-renames", "--name-only", "-z", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z", "--"),
    )
    if baseline is not None:
        if baseline.get("source") != "git":
            raise GitInspectionError("The approved task change baseline is invalid.")
        head = baseline.get("head")
        if not isinstance(head, str) or re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head
        ) is None:
            raise GitInspectionError("The approved Git baseline commit is invalid.")
        expected_prefix = baseline.get("project_prefix")
        current_prefix = _git_bytes(root, "rev-parse", "--show-prefix")
        if current_prefix is None:
            raise GitInspectionError(
                "Required Git inspection failed: git rev-parse --show-prefix"
            )
        normalized_prefix = current_prefix.decode(
            "utf-8", errors="surrogateescape"
        ).replace("\\", "/").strip().strip("/")
        if not isinstance(expected_prefix, str) or normalized_prefix != expected_prefix:
            raise GitInspectionError(
                "The approved Git baseline belongs to a different project path."
            )
        if _git_bytes(root, "merge-base", "--is-ancestor", head, "HEAD") is None:
            raise GitInspectionError(
                "The approved Git baseline is no longer an ancestor of HEAD."
            )
        commands = (
            (
                "diff",
                "--relative",
                "--no-renames",
                "--name-only",
                "-z",
                head,
                "HEAD",
                "--",
            ),
            *commands,
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
    if baseline is not None:
        expected_submodules = baseline.get("submodules", {})
        if not isinstance(expected_submodules, dict):
            raise GitInspectionError("The approved Git submodule baseline is invalid.")
        expected_submodule_oids = baseline.get("submodule_oids", {})
        if (
            not isinstance(expected_submodule_oids, dict)
            or set(expected_submodule_oids) != set(expected_submodules)
        ):
            raise GitInspectionError("The approved Git submodule OIDs are invalid.")
        current_submodules = _gitlink_paths(root)
        if set(current_submodules) != set(expected_submodules):
            raise GitInspectionError(
                "The approved Git submodule set changed; revise and approve the plan again."
            )
        for name, nested_baseline in sorted(expected_submodules.items()):
            if not isinstance(name, str) or not name:
                raise GitInspectionError("The approved Git submodule path is invalid.")
            nested_root = _materialized_submodule_root(root, name)
            if current_submodules[name] != expected_submodule_oids.get(name):
                if nested_root is None:
                    raise GitInspectionError(
                        f"Git submodule commit changed without a materialized tree: {name}"
                    )
                current_head = _git_bytes(
                    nested_root,
                    "rev-parse",
                    "--verify",
                    "HEAD",
                )
                if (
                    current_head is None
                    or current_head.decode("ascii", errors="strict").strip()
                    != current_submodules[name]
                ):
                    raise GitInspectionError(
                        f"Git submodule index and materialized commit disagree: {name}"
                    )
            if nested_baseline is None:
                if nested_root is not None:
                    raise GitInspectionError(
                        f"Git submodule materialization changed after approval: {name}"
                    )
                continue
            if not isinstance(nested_baseline, dict) or nested_root is None:
                raise GitInspectionError(
                    f"Git submodule baseline is unavailable after approval: {name}"
                )
            nested_paths = git_changed_path_names(
                nested_root,
                baseline=nested_baseline,
                strict=True,
            )
            paths.update(f"{name}/{nested_path}" for nested_path in nested_paths)
    return sorted(paths)


def _filesystem_changed_path_names(
    root: Path,
    baseline: dict[str, Any],
    *,
    strict: bool,
) -> list[str]:
    entries = baseline.get("entries")
    if (
        baseline.get("format_version") != 1
        or not isinstance(entries, dict)
        or not all(
            isinstance(path, str) and isinstance(digest, str)
            for path, digest in entries.items()
        )
    ):
        if strict:
            raise GitInspectionError("The approved filesystem baseline is invalid.")
        return []
    try:
        current = _filesystem_change_baseline(root)["entries"]
    except OSError as error:
        if strict:
            raise GitInspectionError(
                f"Required filesystem baseline inspection failed: {error}"
            ) from error
        return []
    changed = {
        path
        for path in set(entries) | set(current)
        if entries.get(path) != current.get(path)
    }
    git_present, head_exists = _filesystem_git_state(root, baseline)
    if git_present:
        commands: list[tuple[str, ...]] = [
            ("diff", "--cached", "--relative", "--no-renames", "--name-only", "-z", "--"),
            ("diff", "--relative", "--no-renames", "--name-only", "-z", "--"),
            ("ls-files", "--others", "--exclude-standard", "-z", "--"),
        ]
        if head_exists:
            commands.insert(
                0,
                ("ls-tree", "-r", "--name-only", "-z", "HEAD", "--", "."),
            )
        for arguments in commands:
            output = _git_bytes(root, *arguments)
            if output is None:
                raise GitInspectionError(
                    "Required unborn Git inspection failed: git "
                    + " ".join(arguments)
                )
            changed.update(_normalized_git_names(output))
        if head_exists:
            head = _git_bytes(root, "rev-parse", "--verify", "HEAD")
            if head is None:
                raise GitInspectionError("Required Git transition HEAD is unavailable.")
            changed.update(
                _git_tree_path_names(
                    root,
                    commit=head.decode("ascii").strip(),
                    display_prefix="",
                    ancestors=frozenset(),
                )
            )
        changed.update(
            _git_index_submodule_path_names(
                root,
                display_prefix="",
                ancestors=frozenset(),
            )
        )
    return sorted(changed)


def _filesystem_git_state(
    root: Path,
    baseline: dict[str, Any],
) -> tuple[bool, bool]:
    context_kind = baseline.get("git_context")
    was_unborn = baseline.get("git_unborn") is True or context_kind == "unborn"
    context = _validated_git_context(root, strict=was_unborn)
    if context is None:
        if was_unborn or (root / ".git").exists():
            raise GitInspectionError(
                "The approved filesystem baseline Git context is unavailable."
            )
        return False, False
    if context_kind == "none":
        raise GitInspectionError(
            "Git was initialized after the filesystem task baseline was approved; "
            "the task must restart from a Git-backed approval."
        )
    if was_unborn:
        expected_prefix = baseline.get("project_prefix")
        if not isinstance(expected_prefix, str) or context[1] != expected_prefix:
            raise GitInspectionError(
                "The approved unborn Git baseline belongs to a different project path."
            )
    return True, _git_bytes(root, "rev-parse", "--verify", "HEAD") is not None


def _git_changed_paths(
    root: Path,
    *,
    baseline: dict[str, Any] | None = None,
) -> list[Path]:
    paths = [
        root / relative_name
        for relative_name in git_changed_path_names(
            root,
            baseline=baseline,
            strict=baseline is not None,
        )
    ]
    return [path for path in paths if _is_regular_file(path)]


def _is_supported_source_file(root: Path, path: Path) -> bool:
    if not _is_regular_file(path) or any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts):
        return False
    return path.suffix.lower() in _TEXT_SUFFIXES or path.name.startswith(".env")


def _python_syntax_failures(
    documents: list[tuple[str, str, bytes]],
) -> list[dict[str, str]]:
    failures = []
    for name, snapshot, content in documents:
        if Path(name).suffix != ".py":
            continue
        try:
            text = content.decode("utf-8")
            compile(text, name, "exec")
        except (SyntaxError, UnicodeDecodeError) as error:
            line = getattr(error, "lineno", None)
            failures.append(
                {
                    "category": "syntax",
                    "location": _snapshot_location(name, snapshot, line),
                    "message": str(error),
                }
            )
    return failures


def _secret_findings(
    documents: list[tuple[str, str, bytes]],
) -> list[dict[str, str]]:
    findings = []
    for name, snapshot, content in documents:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _PRIVATE_KEY.search(line) or _SECRET_ASSIGNMENT.search(line):
                findings.append(
                    {
                        "category": "secret",
                        "location": _snapshot_location(name, snapshot, line_number),
                        "message": "Possible hard-coded credential or private key.",
                    }
                )
    return findings


def _snapshot_location(name: str, snapshot: str, line: int | None = None) -> str:
    location = name if snapshot == "worktree" else f"{name} [{snapshot}]"
    return f"{location}:{line}" if line else location


def _location(root: Path, path: Path, line: int | None = None) -> str:
    try:
        location = path.relative_to(root).as_posix()
    except ValueError:
        location = path.name
    return f"{location}:{line}" if line else location


def _git_whitespace_check(root: Path, arguments: tuple[str, ...], name: str) -> dict[str, str]:
    if _validated_git_context(root, strict=False) is None:
        return {"name": name, "status": "not-run", "detail": "not a Git repository"}
    process = _run_git(root, *arguments)
    if process is None:
        return {"name": name, "status": "failed", "detail": "Git is unavailable"}
    if process.returncode == 0:
        return {"name": name, "status": "passed"}
    return {
        "name": name,
        "status": "failed",
        "detail": (
            process.stdout.decode("utf-8", errors="replace").strip()
            or process.stderr.decode("utf-8", errors="replace").strip()
            or "git diff --check failed"
        ),
    }
