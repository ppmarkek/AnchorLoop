# Changelog

All notable AnchorLoop changes are documented here. npm releases are immutable;
an entry marked **Unreleased** describes repository state, not production npm
availability.

## 0.2.0 - Unreleased

Published production remains `anchorloop@0.1.0` until the signed `v0.2.0` tag
passes the complete release workflow.

### Added

- compare-and-apply recovery tied to exact before-state content, size, mode,
  and digest;
- cross-platform project locking, durable transaction journals, ordered event
  outbox delivery, bounded receipts, and explicit recovery diagnostics;
- core Python validation for task, ownership, verification, metrics, recall,
  and closed-task integrity;
- actual-diff risk escalation before review and precommit, with explicit
  audited overrides for reviewed CAREFUL paths;
- FAST, STANDARD, and CAREFUL ownership modes with close-relative delayed
  recall and explicit approval evidence;
- project/global portable skill installation for Agent Skills, Codex, Cursor,
  Gemini CLI, Claude Code, and OpenCode;
- packed-artifact and registry-backed lifecycle smoke checks;
- migration guidance from `0.1.0` and this changelog.

### Changed

- recovery completes an interrupted project or skill transaction and stops the
  current call without automatically running the newly requested mutation;
- release publication is OIDC-only and requires a verified signed annotated
  tag, green exact-tag CI, an unpublished exact npm version, and matching npm
  `gitHead`;
- generated local skill installations are ignored and are no longer repository
  source of truth;
- the npm package no longer depends recursively on `anchorloop@0.1.0`.

### Compatibility

- `.anchor/` remains the project workflow source of truth and must not be
  deleted during upgrade;
- `add --apply` refreshes managed support files while preserving existing task,
  rule, approval, and audit records;
- locally modified installed skill files are not overwritten unless the user
  reviews the diff and explicitly chooses `--force`;
- legacy rules without approval-time integrity evidence require explicit
  supersession rather than silent activation.

See [the 0.1.0 to 0.2.0 migration guide](docs/MIGRATION_0.2.md).

## 0.1.0 - Published

- Initial public npm production release of the local, agent-neutral AnchorLoop
  workflow and pinned skill adapter.
