# Security policy

## Supported versions

| Version | Supported |
|---|---|
| `0.2.x` | Unreleased release candidate |
| `0.1.x` | Security fixes only |

Published production remains `anchorloop@0.1.0`. Version `0.2.0` is an
unreleased release candidate until the complete signed-tag and staged registry
workflow succeeds. New security work is developed on the current `0.2.x`
candidate; the published `0.1.x` line receives security fixes only.

## Reporting a vulnerability

Please do not publish exploit details in a public issue. Use the repository's
private vulnerability-reporting channel when it is available. If it is not
available, open a public issue that asks only for a private reporting channel;
do not include a proof of concept or sensitive project data.

Useful reports include the affected AnchorLoop version, a minimal reproduction,
impact, and any suggested mitigation.

## Scope

State integrity, path traversal, accidental data loss, approval provenance,
unsafe installer behavior, and disclosure of local paths or secrets are
security-relevant areas for this project.

## Local trust boundary

AnchorLoop rejects symlink/reparse traversal at each managed path component,
serializes project mutations, and journals state/event and skill-install
operations for idempotent recovery. These controls protect against accidental
interruption and common path substitution; they are not a sandbox against a
malicious process running concurrently as the same OS user. Such a process can
race filesystem checks, invoke the CLI, or alter local evidence after access is
granted. Run untrusted agents in an OS/container boundary and use a separate
trusted approval channel when identity or authorization matters.

`anchor doctor` is read-only unless `--repair` is supplied. Recovery artifacts
(`.anchor/project.lock`, `.anchor/transactions/`, and `.anchor/outbox/`) and
all generated cache paths must remain ignored and must not be committed.
