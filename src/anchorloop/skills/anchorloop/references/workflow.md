# AnchorLoop workflow reference

## Install this adapter

The Python package keeps the standalone CLI. Install its portable skill adapter
only when a project or user wants agent discovery. The installer supplies
`{{ANCHOR_COMMAND}}` as the command runner in the installed skill:

~~~powershell
# Cross-framework project skill (recommended)
{{ANCHOR_COMMAND}} install --project --platform agents --apply

# Optional Codex-specific project location
{{ANCHOR_COMMAND}} install --project --platform codex --apply
~~~

The project option writes only:

~~~text
.agents/skills/anchorloop/      # platform=agents
.codex/skills/anchorloop/       # platform=codex
~~~

The installer copies packaged Markdown and an ownership marker. It does not
alter `.anchor/`, application code, `AGENTS.md`, hooks, or Graphify settings.
Use `{{ANCHOR_COMMAND}} uninstall --project --platform agents --apply` to remove only
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
~~~

Keep `.anchor/.gitignore` entries for `cache/`, `logs/`, and
`graphify/query-history.jsonl`. After changing an ignore rule, verify it with
`git check-ignore -v --no-index <cache-path>`.

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

## Quality evidence

`{{ANCHOR_COMMAND}} precommit` records deterministic checks and a workspace fingerprint.
If the fingerprint differs before verification or close, AnchorLoop resets the
task to `review_ready`; review the code and run `anchor precommit` again.

## Failed verification

Record the result first:

~~~powershell
{{ANCHOR_COMMAND}} verify --by "Engineer name" --result fail --reason "Observed issue"
~~~

Then choose the narrowest valid revision:

~~~powershell
# The original approved scope is still valid
{{ANCHOR_COMMAND}} revise --target implement --reason "Fix the observed behaviour"

# The plan or scope decision changed
{{ANCHOR_COMMAND}} revise --target plan --reason "Choose a different approach"
{{ANCHOR_COMMAND}} plan --summary "Revised approach"
{{ANCHOR_COMMAND}} approve --by "Engineer name"
~~~

## Rule migration

Approved rule documents created by current AnchorLoop versions carry an
approval-time digest. If an older active rule lacks that digest, it cannot
govern a new task. Propose and approve a replacement in the same category,
then migrate it explicitly:

~~~powershell
{{ANCHOR_COMMAND}} rules supersede <old-rule-id> <new-rule-id> --by "Engineer name" --reason "Migration reason"
~~~

## Trust boundary

Without a trusted host adapter or separate approval channel, AnchorLoop is an
auditable workflow guardrail, not an access-control boundary. A terminal-capable
agent can invoke commands, so agents must not treat `--by` as authentication.
