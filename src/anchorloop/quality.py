from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any


_SKIP_DIRECTORIES = {".anchor", ".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", "graphify-out"}
_TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".rb", ".php", ".sh", ".json", ".yaml", ".yml", ".toml", ".env", ".md"}
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][^\"']{8,}[\"']"
)


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

    Git repositories use HEAD, staged and unstaged binary diffs, plus the
    contents of untracked files. A non-Git directory falls back to a recursive
    local snapshot while excluding generated and Anchor-owned directories.
    """

    git_fingerprint = _git_workspace_fingerprint(root)
    if git_fingerprint is not None:
        return git_fingerprint

    digest = hashlib.sha256()
    digest.update(b"anchorloop-workspace-v1\0filesystem\0")
    files = sorted(_fingerprint_files(root), key=lambda path: path.relative_to(root).as_posix())
    for path in files:
        _update_digest_with_file(digest, root, path)
    return {
        "algorithm": "sha256",
        "digest": f"sha256:{digest.hexdigest()}",
        "source": "filesystem",
        "files": len(files),
        "head": None,
    }


def _git_workspace_fingerprint(root: Path) -> dict[str, Any] | None:
    if not (root / ".git").exists():
        return None

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
    untracked = _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z")
    if staged is None or unstaged is None or untracked is None:
        return None

    digest = hashlib.sha256()
    digest.update(b"anchorloop-workspace-v1\0git\0")
    _update_digest_value(digest, b"head", head or b"<unborn>")
    _update_digest_value(digest, b"staged", staged)
    _update_digest_value(digest, b"unstaged", unstaged)

    untracked_count = 0
    for encoded_name in untracked.split(b"\0"):
        if not encoded_name:
            continue
        path = root / encoded_name.decode("utf-8", errors="surrogateescape")
        if path.is_file() and not _is_anchor_owned_path(root, path):
            _update_digest_with_file(digest, root, path)
            untracked_count += 1

    return {
        "algorithm": "sha256",
        "digest": f"sha256:{digest.hexdigest()}",
        "source": "git",
        "files": untracked_count,
        "head": head.decode("utf-8", errors="replace").strip() if head else None,
    }


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
    digest.update(b"file\0")
    _update_digest_value(digest, b"path", relative_path)
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        digest.update(b"<unreadable>")
    digest.update(b"\0")


def _fingerprint_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts)
    ]


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


def _git_changed_paths(root: Path) -> list[Path]:
    commands = (
        ("diff", "--name-only", "HEAD"),
        ("diff", "--cached", "--name-only"),
        ("ls-files", "--others", "--exclude-standard"),
    )
    paths: dict[Path, None] = {}
    for arguments in commands:
        process = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, text=True, check=False
        )
        if process.returncode != 0:
            continue
        for relative_name in process.stdout.splitlines():
            path = root / relative_name
            if path.is_file():
                paths[path] = None
    return list(paths)


def _is_supported_source_file(root: Path, path: Path) -> bool:
    if not path.is_file() or any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts):
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
