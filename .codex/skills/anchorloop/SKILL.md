---
name: anchorloop
description: Guides agents through AnchorLoop's engineer-controlled, local workflow without owning its state. Use when a repository contains .anchor/, the user asks to follow AnchorLoop, or an AI-assisted coding task needs recorded briefs, approvals, rules, quality evidence, or verification.
---

# AnchorLoop

AnchorLoop is agent-neutral. This skill is only a thin adapter: the local
command runner and the project's `.anchor/` directory are the source of truth.

The installer supplies `npx --yes anchorloop@0.1.0` as the command runner. Use that
exact prefix for every AnchorLoop command below. Do not replace a pinned npx
runner with `@latest`, add a project-local npm cache, or install packages into
the repository.

## First action

1. Run `npx --yes anchorloop@0.1.0 status` from the project root.
2. Read `.anchor/next-action.md` when it exists.
3. Follow only the action allowed by the recorded task state.

If AnchorLoop is not configured, explain that `npx --yes anchorloop@0.1.0 add --apply` will create
project-local state. Do not create it unless the engineer has asked for setup.

## Engineer-owned gates

Do not impersonate an engineer or claim that a human has approved work.

- Do not run `npx --yes anchorloop@0.1.0 approve`, `npx --yes anchorloop@0.1.0 rules approve`,
  `npx --yes anchorloop@0.1.0 rules supersede`, `npx --yes anchorloop@0.1.0 verify`, or
  `npx --yes anchorloop@0.1.0 close`, or `npx --yes anchorloop@0.1.0 outcome` unless the engineer explicitly asks for
  that exact recorded action.
- `--by` is an audit attribution, not proof of identity. Preserve the supplied
  provenance and do not invent it.
- Verification values for `--result`, `--reason`, and `--recall` must reflect
  the engineer's observed outcome and explanation; do not infer or prefill them.
- Do not edit `.anchor/` JSON files by hand to bypass a transition or rule.

## Normal coding flow

Use the CLI to record the real workflow. Let `AUTO` select the minimum risk
mode. For a normal `STANDARD` task, obtain the engineer's actual plan inputs;
never invent the human artifact or comprehension statement:

~~~text
npx --yes anchorloop@0.1.0 start "short task title"
npx --yes anchorloop@0.1.0 brief --by "Engineer name" --outcome "..." --scope "..." --constraints "..." --invariant "..." --uncertainty "..."
npx --yes anchorloop@0.1.0 plan --summary "..." --mode AUTO --task-type "..." --approach "..." --alternative "..." --risk "..." --verification "..." --human-artifact "..." --comprehension "..." --by "Engineer name"
npx --yes anchorloop@0.1.0 approve --by "Engineer name"
npx --yes anchorloop@0.1.0 implement
npx --yes anchorloop@0.1.0 review
npx --yes anchorloop@0.1.0 precommit
npx --yes anchorloop@0.1.0 verify --by "Engineer name" --result pass --reason "..." --recall "..."
npx --yes anchorloop@0.1.0 close
~~~

`AUTO` recommends `FAST` only for low-risk documentation/chore work,
`STANDARD` for ordinary changes, and `CAREFUL` for sensitive work such as
authentication, payments, secrets, migrations, concurrency, infrastructure,
destructive changes, public APIs, or new dependencies. `CAREFUL` also requires
`--rollback-mitigation`. An explicit downgrade requires
`--mode-override-reason`; surface that decision instead of hiding it.

The human artifact is a real engineer-created acceptance case, prediction,
decision note, or similar piece of reasoning. `--comprehension` and verify's
`--recall` are the engineer's own explanations. Ask for missing input and keep
the gate pending; do not generate answers on the engineer's behalf.

If verification fails, preserve the failure and use `npx --yes anchorloop@0.1.0 revise` to return
to implementation or planning. If code changes after `npx --yes anchorloop@0.1.0 precommit`, rerun
review and the quality gate before verification.

After a `CAREFUL` task closes, AnchorLoop schedules recall **24 hours after
that close time**. Run `npx --yes anchorloop@0.1.0 status` and inspect
`pending_recalls` (or the closed task's `recall_due_at`). When that time has
passed and the engineer explicitly supplies a response, record delayed recall
with `npx --yes anchorloop@0.1.0 recall --task <id> --by "Engineer name" --response
"..." --score <0-5>`. Never backdate, fabricate, or auto-complete recall.

Only when the engineer supplies an observed follow-up, record defects,
rollback, corrective refactor, and notes with `npx --yes anchorloop@0.1.0 outcome`.
`npx --yes anchorloop@0.1.0 report --format json|csv` is read-only and aggregates local
closed-task pilot fields; treat reported time/token/model/outcome values as
audit data, not trusted provider telemetry.

## Rules and evidence

- Treat rules as inactive until the engineer records `npx --yes anchorloop@0.1.0 rules approve`.
- Never replace an active rule silently; use the explicit supersede command
  only with an engineer-provided reason.
- Keep the patch within the recorded brief and surface a changed scope before
  editing code.
- Use `npx --yes anchorloop@0.1.0 precommit` before asking the engineer to verify behaviour.
- Treat generated cache as local-only: never stage or commit it. Before a
  cache-producing tool runs, verify that its exact output path is ignored by
  Git; follow the cache policy in the workflow reference.
- Treat `.anchor/project.lock`, `.anchor/transactions/`, and
  `.anchor/outbox/` as runtime recovery artifacts. They must stay ignored and
  must not be staged or copied into reports.

## Optional integrations

Graphify is separate and opt-in. Do not install it, create a graph, or change
host configuration without explicit engineer approval.

For command details and recovery guidance, see
[the workflow reference](references/workflow.md).
