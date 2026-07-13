# AnchorLoop 0.1 release plan

Status: release candidate; public npm bootstrap pending
Scope: local, agent-neutral workflow integrity and human-ownership loop

## Product intent

AnchorLoop lets an AI agent implement code without silently taking ownership
of intent, trade-offs, risk, or acceptance away from the engineer. The local
CLI and `.anchor/` records are the source of truth. An installed skill is a
thin discovery/instruction adapter around that same core.

> The agent may write the code. The engineer owns why it exists, which
> trade-off was chosen, what could fail, and how the result is verified.

## What 0.1 implements

| Area | Release behavior |
|---|---|
| Distribution | Standalone Python CLI plus an npm launcher that installs a Codex or generic Agent Skills adapter. |
| Workflow | `start → brief → plan → approve → implement → review → precommit → verify → close`, with explicit revision after failure. |
| Human ownership | AUTO risk recommendation, FAST/STANDARD/CAREFUL modes, engineer-authored artifact and comprehension fields, rollback mitigation for CAREFUL, immediate/delayed recall, post-completion outcomes, and local JSON/CSV report. |
| Integrity | Approval digests bind the brief, brief attribution, plan, human-ownership record, recall policy, and active ruleset. |
| Quality evidence | Local syntax/security/whitespace baseline plus a materialized workspace fingerprint; project-specific tool profiles are not yet configured by AnchorLoop. |
| Concurrency/recovery | Cross-platform project lock, durable redo journal, ordered event outbox, bounded receipts, explicit `doctor --repair`, and fail-closed consistent reads. |
| Skill lifecycle | Previewable project/user install, update, status, and uninstall with owned-file digests, per-destination lock, durable recovery journal, and marker-last commit. |
| Filesystem boundary | Managed paths reject symlinks and Windows reparse points; writes are unique-temp, fsynced, and atomically replaced. |
| Cache policy | Project-local cache, bytecode, npm cache, transaction, lock, and outbox artifacts are ignored and never treated as evidence. |
| Portability | The npm launcher supplies an exact pinned display runner so installed skill instructions and generated next actions do not depend on a global `anchor` executable. |

## Architecture

~~~mermaid
flowchart LR
  E[Engineer] --> H[Agent host or terminal]
  H --> S[Optional installed skill]
  S --> C[AnchorLoop CLI]
  H --> C
  C --> L[Project lock]
  L --> T[Redo journal and event outbox]
  T --> A[.anchor state and audit log]
  C --> Q[Local quality evidence]
  Q --> A
~~~

The adapter never owns state. Graphify, native host plugins, hooks, MCP, and
external research are optional future integrations; 0.1 does not install or
invoke them automatically.

## Human-ownership contract

`AUTO` chooses the minimum recommended mode:

| Mode | Intended use | Required ownership evidence |
|---|---|---|
| FAST | Familiar, low-risk documentation or chore | Brief, plan, approval, quality result, engineer verification |
| STANDARD | Ordinary feature/fix work | Chosen approach, rejected alternative, primary risk, verification strategy, engineer-created artifact, baseline comprehension, immediate recall |
| CAREFUL | Auth, payments, secrets, migrations, concurrency, infrastructure, destructive work, public APIs, new dependencies | STANDARD evidence plus rollback/mitigation and delayed recall scheduled after close |

An explicit downgrade requires a recorded reason. `--by` is audit attribution,
not authentication. A trusted host adapter or separate approval channel is
required before approval identity can be treated as an access-control claim.

## Release invariants

1. No mutating command runs outside the project lock and transaction wrapper.
2. State, next action, and ordered global events cannot be presented as a
   partially committed command.
3. Recovery replays only a validated journal inside its exact managed root.
4. A task cannot implement without an intact engineer brief, ownership record,
   ruleset snapshot, and approval digest.
5. Changed approved input invalidates approval; changed checked content
   invalidates quality evidence.
6. A CAREFUL delayed-recall schedule is approval-bound and cannot be backdated
   by editing a closed task.
7. Agents never fabricate human artifacts, comprehension answers, approval,
   rule activation, verification, close, or delayed recall.
8. Installer `--force` can replace only AnchorLoop-owned assets and never
   relaxes the filesystem boundary.
9. Generated cache and recovery internals are ignored and never committed as
   project evidence.

## Supported command surface

~~~text
anchor init|add [--apply]
anchor install|uninstall [--project] [--platform agents|codex] [--apply]
anchor status
anchor doctor [--strict|--repair]
anchor start, brief, plan, approve, implement, review, precommit
anchor verify, revise, close, recall, outcome, report
anchor rules list|propose|approve|supersede
anchor agent detect|setup|status
~~~

The npm form runs the same surface through a pinned command such as
`npx --yes anchorloop@0.1.0`. README and the bundled skill contain the full
structured plan/verification examples.

## Production release gates

Code is release-ready only when all of these are true:

- Python tests pass on supported versions, including Windows lock/recovery;
- Node 18/20/22 passes on Ubuntu and Windows;
- the canonical Python version, npm version, and release tag match;
- wheel install and local packed-tarball lifecycle pass from a clean temp root;
- the npm tarball contains every runtime module, skill asset, and README link
  target, with no cache, bytecode, build output, or project dependency;
- a GitHub-verified signed annotated tag points to the green commit;
- npm provenance publishing succeeds;
- the exact public registry version passes install, full task lifecycle,
  uninstall, and residue checks.

The unscoped `anchorloop` package does not yet exist in npm. Reserve it once
with a lower, version-consistent bootstrap version such as `0.0.0`; do not
manually consume the intended alpha version because npm cannot republish an
immutable version with provenance. Then configure the protected `npm-release`
environment and npm trusted publisher for `.github/workflows/release.yml` and
publish `0.1.0` from its signed tag. Later releases remain tag-driven and
OIDC-only.

## Pilot evidence

Closed tasks record mode, task type, wall time, optional turns/tokens/active
minutes, optional provider/model identity, immediate comprehension, and delayed
recall score. These values are locally auditable but reported, not trusted
telemetry.

Before claiming that AnchorLoop preserves understanding without slowing work,
run a pilot across task types and modes and compare at least:

- completion and active time;
- turns and token volume;
- verification failure/revision rate;
- delayed recall score;
- post-completion defects, rollback, and corrective refactor work.

Outcome capture and aggregate reporting are implemented locally; they still do
not prove the central product hypothesis before a real comparative pilot.

## Deferred, not implied

- authenticated human identity and remote authorization;
- project-specific formatter/linter/type/test/dependency command profiles;
- automatic Graphify installation or graph generation;
- skill catalogue search and third-party package installation;
- native IDE hooks, slash commands, MCP server, hosted dashboard, deployment,
  merge, or multi-user account management;
- automatic reminders or background schedulers for delayed recall.

These may be built as adapters or later vertical slices. None may replace the
local CLI/state contract or silently broaden agent authority.
