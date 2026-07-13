# Portable skill adapter

AnchorLoop is a standalone, agent-neutral CLI. The portable skill is a
distribution and discovery layer around that CLI; it is not a second workflow
engine and it never becomes the source of truth for task state.

## Install

Install the Python package first, then explicitly apply a previewed skill
installation:

~~~powershell
# Cross-framework Agent Skills location (recommended)
anchor install --project --platform agents --apply

# Explicit host-specific location
anchor install --project --platform codex --apply
~~~

Without `--project`, the same command installs into the current user's
`.agents/skills/anchorloop/` or `.codex/skills/anchorloop/` directory.

The copied package contains:

~~~text
SKILL.md
references/workflow.md
.anchorloop-skill.json
~~~

The marker stores a SHA-256 digest for every installed asset. By default,
install and uninstall stop if an installer-owned file was edited locally; this
preserves local work and prevents broad deletion. Use `--force` only when
those edits are intentionally being replaced or removed.

Uninstall removes only unchanged installer-owned files:

~~~powershell
anchor uninstall --project --platform agents --apply
~~~

## Boundaries

The installer never changes:

- application source code or dependencies;
- `.anchor/` state;
- `AGENTS.md`, hooks, MCP configuration, or IDE settings;
- Graphify installation, graph generation, or Graphify settings.

Always-on host integration is deliberately a separate future feature because
it can alter how an agent behaves in every session.

## Legacy rule migration

An old approved rule without an approval-time digest is treated as
migration-required, not silently trusted. The engineer must propose and
approve a replacement in the same category, then record an explicit
`anchor rules supersede <old> <new> --by <engineer> --reason <text>` action.

## Workflow contract

The installed skill directs an agent to run `anchor status` and read
`.anchor/next-action.md`. It must not edit state JSON directly or act as the
engineer at approval, rule, verification, or close gates.

The CLI records `audit` or `interactive-tty` provenance. The latter requires
an interactive terminal and a typed `APPROVE` confirmation, but neither is a
trusted identity channel by itself; without a separate trusted adapter,
AnchorLoop is an auditable workflow guardrail rather than an access-control
boundary.

## Graphify

Graphify is an optional navigation provider, not a required dependency of the
skill installer. AnchorLoop can retain Graphify metadata and ignore rules in a
project without installing, configuring, or invoking Graphify. Any such action
requires separate engineer approval.
