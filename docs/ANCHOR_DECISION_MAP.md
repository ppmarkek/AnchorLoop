# AnchorLoop release decision map

This map separates resolved 0.1 decisions from external release blockers and
post-release product questions.

## Resolved for 0.1

| Decision | Resolution |
|---|---|
| Core runtime | Python 3.11+ owns workflow/state; the npm package is a thin Node 18+ launcher around bundled Python source. |
| Source of truth | The CLI and `.anchor/` state, never a Codex-only skill, model, provider, or slash-command format. |
| Skill distribution | Project or user scope; generic `.agents/skills` and explicit `.codex/skills`; preview/apply and owned-file uninstall. |
| Version source | `src/anchorloop/version.py`; Python metadata reads it and npm/tag values are checked against it. |
| Mutation model | One interprocess lock plus validated redo journal and ordered event outbox for every project mutation. |
| Quality fingerprint | Materialized tracked/non-ignored files, recursively including submodules; Git metadata is diagnostic only. |
| Human modes | AUTO recommendation with FAST/STANDARD/CAREFUL, explicit downgrade reason, human artifact/comprehension, and CAREFUL delayed recall. |
| Cache/recovery state | Ignored local runtime data; never committed as workflow evidence. |
| Trust statement | `--by` and interactive TTY confirmation are auditable provenance, not authenticated identity. |

## External release blocker

### npm name bootstrap

`anchorloop` currently returns E404 in the public registry. A maintainer must
either reserve it with a lower, version-consistent bootstrap release (for
example `0.0.0`) or switch every manifest, runner, workflow, and document to an
owned scope. The bootstrap must not consume the intended alpha version: npm
versions are immutable, while `0.1.0` must be published from its signed tag
with OIDC provenance. No code path may claim that `npx anchorloop install`
works publicly before registry smoke succeeds.

## Decisions before public beta

### Trusted approval channel

Choose a host adapter or separate channel that can bind approval to an
authenticated human while leaving the local audit contract usable without it.

### Project-specific quality profiles

Define explicit, engineer-approved formatter, linter, type-checker, test, and
dependency commands per stack. Commands, timeouts, network behavior, and
evidence must be visible; AnchorLoop must not execute repository-supplied
commands merely because it discovered them.

### Outcome measurement and export

Add post-completion defect/rollback/refactor outcomes and a privacy-preserving
aggregate export for model × mode pilots. Reported token/time fields must never
be presented as provider-verified telemetry.

### State evolution

Define schema migration policy and compatibility promises before a stable
release. Re-running setup currently appends new managed ignore entries while
preserving custom lines; migration must remain explicit and recoverable.

### Optional navigation and host integrations

Evaluate Graphify, hooks, native slash commands, and MCP only as opt-in thin
adapters. Record dependency, cache, privacy, and permission costs before any
installation or invocation.
