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

### Publish the immutable 0.2.0 version

`anchorloop@0.1.0` remains published production. The current release branch is
the unreleased `0.2.0` release candidate. The release flow requires the signed
annotated tag commit to be contained in `origin/main` and to pass exact-tag CI
before the exact tarball is staged under `next` through a Trusted Publisher
configured for stage-only `npm stage publish`. A maintainer must download and
inspect the staged artifact, approve it with 2FA, then dispatch the read-only
exact-version registry lifecycle, verify that `next` points to that version,
and check npm `gitHead`. Only after those checks pass may a maintainer
interactively run `npm dist-tag add anchorloop@0.2.0 latest` with 2FA. The
workflow stores no npm token and never promotes `latest` automatically. Until
that sequence completes, no document may claim that `0.2.0` is published or
available from npm `latest`.

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
