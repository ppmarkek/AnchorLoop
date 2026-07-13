---
name: anchorloop
description: Guides agents through AnchorLoop's engineer-controlled, local workflow without owning its state. Use when a repository contains .anchor/, the user asks to follow AnchorLoop, or an AI-assisted coding task needs recorded briefs, approvals, rules, quality evidence, or verification.
---

# AnchorLoop

AnchorLoop is agent-neutral. This skill is only a thin adapter: the local
`anchor` CLI and the project's `.anchor/` directory are the source of truth.

## First action

1. Run `anchor status` from the project root.
2. Read `.anchor/next-action.md` when it exists.
3. Follow only the action allowed by the recorded task state.

If AnchorLoop is not configured, explain that `anchor add --apply` will create
project-local state. Do not create it unless the engineer has asked for setup.

## Engineer-owned gates

Do not impersonate an engineer or claim that a human has approved work.

- Do not run `anchor approve`, `anchor rules approve`, `anchor rules supersede`,
  `anchor verify`, or `anchor close` unless the engineer explicitly asks for
  that exact recorded action.
- `--by` is an audit attribution, not proof of identity. Preserve the supplied
  provenance and do not invent it.
- Do not edit `.anchor/` JSON files by hand to bypass a transition or rule.

## Normal coding flow

Use the CLI to record the real workflow:

~~~text
anchor start "short task title"
anchor brief ...
anchor plan --summary "..."
anchor approve --by "Engineer name"
anchor implement
anchor review
anchor precommit
anchor verify --by "Engineer name" --result pass --reason "..."
anchor close
~~~

If verification fails, preserve the failure and use `anchor revise` to return
to implementation or planning. If code changes after `anchor precommit`, rerun
review and the quality gate before verification.

## Rules and evidence

- Treat rules as inactive until the engineer records `anchor rules approve`.
- Never replace an active rule silently; use the explicit supersede command
  only with an engineer-provided reason.
- Keep the patch within the recorded brief and surface a changed scope before
  editing code.
- Use `anchor precommit` before asking the engineer to verify behaviour.
- Treat generated cache as local-only: never stage or commit it. Before a
  cache-producing tool runs, verify that its exact output path is ignored by
  Git; follow the cache policy in the workflow reference.

## Optional integrations

Graphify is separate and opt-in. Do not install it, create a graph, or change
host configuration without explicit engineer approval.

For command details and recovery guidance, see
[the workflow reference](references/workflow.md).
