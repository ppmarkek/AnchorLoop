from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


_SKIP_DIRECTORIES = {".anchor", ".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
_TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".rb", ".php", ".sh", ".json", ".yaml", ".yml", ".toml", ".env", ".md"}
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][^\"']{8,}[\"']"
)


def run_precommit(root: Path, *, active_categories: set[str]) -> dict[str, Any]:
    """Run small, local checks that are safe before project-specific tools exist."""

    findings: list[dict[str, str]] = []
    checks: list[dict[str, str]] = []
    files = list(_source_files(root))

    syntax_failures = _python_syntax_failures(files)
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
        secret_findings = _secret_findings(files)
        if secret_findings:
            findings.extend(secret_findings)
            checks.append({"name": "secret-baseline", "status": "failed"})
        else:
            checks.append({"name": "secret-baseline", "status": "passed"})

    checks.append(_git_whitespace_check(root, ("diff", "--check"), "git-diff-check"))
    checks.append(_git_whitespace_check(root, ("diff", "--cached", "--check"), "git-cached-diff-check"))

    return {
        "status": "blocked" if findings or any(check["status"] == "failed" for check in checks) else "passed",
        "checks": checks,
        "findings": findings,
        "advisories": [
            "No project-specific formatter, linter, type checker, test runner, or dependency scanner is configured yet.",
            "DRY, KISS, YAGNI, SOLID, and architecture findings require concrete diff evidence and engineer review.",
        ],
    }


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


def _python_syntax_failures(files: list[Path]) -> list[dict[str, str]]:
    failures = []
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (SyntaxError, UnicodeDecodeError) as error:
            line = getattr(error, "lineno", None)
            location = f"{path}:{line}" if line else str(path)
            failures.append(
                {
                    "category": "syntax",
                    "location": location,
                    "message": str(error),
                }
            )
    return failures


def _secret_findings(files: list[Path]) -> list[dict[str, str]]:
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
                        "location": f"{path}:{line_number}",
                        "message": "Possible hard-coded credential or private key.",
                    }
                )
    return findings


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
