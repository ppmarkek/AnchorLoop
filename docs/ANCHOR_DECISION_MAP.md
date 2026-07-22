# AnchorLoop release decision map

This map separates resolved 0.2 decisions from external release gates and
post-release product questions.

## Resolved for 0.2

| Decision | Resolution |
|---|---|
| Core runtime | Python 3.11+ owns workflow/state; the npm package is a thin Node 18+ launcher around bundled Python source. |
| Source of truth | The CLI and `.anchor/` state, never a Codex-only skill, model, provider, or slash-command format. |
| Skill distribution | Project or user scope across the six documented filesystem destinations; preview/apply and owned-file uninstall. Real-host discovery remains Experimental. |
| Version source | `src/anchorloop/version.py`; Python metadata reads it and npm/tag values are checked against it. |
| Mutation model | One interprocess lock plus validated redo journal and ordered event outbox for every project mutation. |
| Quality fingerprint | Materialized tracked/non-ignored files plus authoritative HEAD/index/diff state, recursively including submodules. |
| Human modes | AUTO recommendation with FAST/STANDARD/CAREFUL, explicit downgrade reason, human artifact/comprehension, and CAREFUL delayed recall. |
| Cache/recovery state | Ignored local runtime data; never committed as workflow evidence. |
| Trust statement | `--by` and interactive TTY confirmation are auditable provenance, not authenticated identity. |

## Human-owned release gate

### Maintain the published 0.2.1 version

`anchorloop@0.2.1` is published production. Its signed annotated tag is
contained in `origin/main`, and the release passed exact-tag CI, staged npm
publishing, exact-version registry smoke, and human approval. The workflow
stores no npm token and does not move mutable dist-tags automatically. Keep
automation pinned to `anchorloop@0.2.1` and leave the signed release artifact
unchanged.

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
