# AnchorLoop workflow reference

## Install this adapter

The Python package keeps the standalone CLI. Install its portable skill adapter
only when a project or user wants agent discovery. The installer supplies
`npx --yes anchorloop@0.1.0` as the command runner in the installed skill:

~~~powershell
# Cross-framework project skill (recommended)
npx --yes anchorloop@0.1.0 install --project --platform agents --apply

# Optional Codex-specific project location
npx --yes anchorloop@0.1.0 install --project --platform codex --apply
~~~

The project option writes only:

~~~text
.agents/skills/anchorloop/      # platform=agents
.codex/skills/anchorloop/       # platform=codex
~~~

The installer copies packaged Markdown and an ownership marker. It does not
alter `.anchor/`, application code, `AGENTS.md`, hooks, or Graphify settings.
Use `npx --yes anchorloop@0.1.0 uninstall --project --platform agents --apply` to remove only
unchanged installer-owned files. If a packaged asset was edited locally, the
installer stops and requires an explicit `--force` before replacing or removing
it.

## Local cache

Treat generated cache as local-only; never stage it, commit it, or bypass an
ignore rule with `git add -f`. Before enabling a cache-producing tool, verify
that its precise output path is ignored by the project's root `.gitignore`.
AnchorLoop projects must keep these paths ignored:

~~~text
/cache/
/.cache/
/.anchor/cache/
/.npm/
/.npm-cache/
graphify-out/
__pycache__/
*.py[cod]
~~~

Keep `.anchor/.gitignore` entries for `cache/`, `logs/`,
`graphify/query-history.jsonl`, `project.lock`, `transactions/`, and `outbox/`.
The last three are lock/recovery internals, not project evidence. After
changing an ignore rule, verify it with
`git check-ignore -v --no-index <cache-path>`.

After upgrading an existing AnchorLoop project, an engineer may rerun
`npx --yes anchorloop@0.1.0 add --apply` to append missing managed ignore entries
without replacing custom lines. An ignore rule does not untrack a path that is
already in Git; inspect the index and remove runtime artifacts from it through
the project's normal review process.

## State progression

~~~text
briefing -> planned -> approved -> implementing -> review_ready
-> quality_checked -> verified -> closed
~~~

The engineer brief, recorded approval, rule snapshot, quality evidence, and
verification stay in `.anchor/tasks/active.json`. Do not rewrite that file
manually. AnchorLoop hashes the brief, plan, and pinned ruleset at approval.
If any of them changes afterward, it archives the stale approval and returns
the task to briefing (brief change) or planned (plan/ruleset change) so the
engineer can record a fresh approval.

## Human ownership modes

Use `--mode AUTO` unless the engineer deliberately selects a mode. AUTO
recommends FAST for low-risk documentation/chore work, STANDARD for ordinary
changes, and CAREFUL for sensitive changes such as auth, payments, secrets,
migrations, concurrency, infrastructure, destructive operations, public APIs,
or new dependencies. A downgrade requires a recorded
`--mode-override-reason`.

STANDARD and CAREFUL plans require explicit engineer-owned reasoning:

~~~powershell
npx --yes anchorloop@0.1.0 plan `
  --summary "Bounded implementation summary" `
  --mode AUTO `
  --task-type "feature" `
  --approach "Chosen approach" `
  --alternative "Rejected alternative and why" `
  --risk "Primary failure mode" `
  --verification "How the invariant will be checked" `
  --human-artifact "Actual engineer-created acceptance case or decision note" `
  --comprehension "Engineer's prediction or explanation" `
  --by "Engineer name"
~~~

CAREFUL additionally requires `--rollback-mitigation`. Do not let an agent
invent the human artifact, comprehension statement, or rollback decision. If
those inputs do not exist, the plan gate is intentionally incomplete.

STANDARD and CAREFUL verification includes the engineer's immediate recall:

~~~powershell
npx --yes anchorloop@0.1.0 verify --by "Engineer name" --result pass --reason "Observed result" --recall "Why the approach worked and what would falsify it"
~~~

When known, append reported experiment metadata with `--agent-turns`,
`--input-tokens`, `--output-tokens`, `--active-minutes`, `--agent-provider`,
and `--agent-model`. Provider and model must be supplied together. These are
auditable reported values, not trusted usage telemetry.

A closed CAREFUL task schedules delayed recall **24 hours after close**. After
its immutable `recall_due_at` has passed, record the engineer's response and
0-5 score:

~~~powershell
npx --yes anchorloop@0.1.0 recall --task <task-id> --by "Engineer name" --response "Recalled trade-off and invariant" --score 4
~~~

## Post-completion outcome and pilot report

When the engineer actually observes a post-completion result, record the
latest cumulative defect count and whether rollback or a corrective refactor
was needed:

~~~powershell
npx --yes anchorloop@0.1.0 outcome --task <task-id> --by "Engineer name" --defects 1 --rollback no --corrective-refactor yes --notes "Observed follow-up"
~~~

Do not infer these fields from code or issue text. The local aggregate is
read-only and can be emitted as JSON or CSV:

~~~powershell
npx --yes anchorloop@0.1.0 report --format json
npx --yes anchorloop@0.1.0 report --format csv
~~~

Reported token, time, provider/model, recall, and outcome values are audit
inputs, not provider-verified telemetry.

## Quality evidence

`npx --yes anchorloop@0.1.0 precommit` records deterministic checks and a workspace fingerprint.
If the fingerprint differs before verification or close, AnchorLoop resets the
task to `review_ready`; review the code and run
`npx --yes anchorloop@0.1.0 precommit` again.

## Failed verification

Record the result first:

~~~powershell
npx --yes anchorloop@0.1.0 verify --by "Engineer name" --result fail --reason "Observed issue" --recall "Why the expected behavior did not hold"
~~~

Then choose the narrowest valid revision:

~~~powershell
# The original approved scope is still valid
npx --yes anchorloop@0.1.0 revise --target implement --reason "Fix the observed behaviour"

# The plan or scope decision changed
npx --yes anchorloop@0.1.0 revise --target plan --reason "Choose a different approach"
npx --yes anchorloop@0.1.0 plan --summary "Revised approach" --mode AUTO --task-type "feature" --approach "New approach" --alternative "Rejected alternative" --risk "Primary risk" --verification "Acceptance check" --human-artifact "Engineer's artifact" --comprehension "Engineer's prediction" --by "Engineer name"
npx --yes anchorloop@0.1.0 approve --by "Engineer name"
~~~

## Recovery and diagnosis

All mutating workflow commands are serialized by a project lock and commit
state plus ordered events through a durable redo journal. Read commands refuse
to present a partial transaction. `doctor` is inspect-only by default:

~~~powershell
npx --yes anchorloop@0.1.0 doctor
npx --yes anchorloop@0.1.0 doctor --strict
npx --yes anchorloop@0.1.0 doctor --repair
~~~

Use `--repair` only when the engineer asks to complete an interrupted
transaction or repair a torn final event-log line. It never bypasses an
approval or fabricates workflow evidence.

## Rule migration

Approved rule documents created by current AnchorLoop versions carry an
approval-time digest. If an older active rule lacks that digest, it cannot
govern a new task. Propose and approve a replacement in the same category,
then migrate it explicitly:

~~~powershell
npx --yes anchorloop@0.1.0 rules supersede <old-rule-id> <new-rule-id> --by "Engineer name" --reason "Migration reason"
~~~

## Trust boundary

Without a trusted host adapter or separate approval channel, AnchorLoop is an
auditable workflow guardrail, not an access-control boundary. A terminal-capable
agent can invoke commands, so agents must not treat `--by` as authentication.
