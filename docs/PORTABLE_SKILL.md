# Portable skill adapter

AnchorLoop is a standalone, agent-neutral CLI. The portable skill is a
distribution and discovery layer around that CLI; it is not a second workflow
engine and it never becomes the source of truth for task state.

## Install

For Node.js 18+ and Python 3.11+, the npm shortcut is the fastest route:

~~~powershell
npx anchorloop install
~~~

In an interactive terminal this opens a guided installer: choose the current
project or your user profile; user-global setup then offers Codex, Cursor,
Gemini CLI, Claude Code, OpenCode, the cross-framework Agent Skills standard,
or all native agent locations. The installer shows every destination and asks for a
final confirmation before it writes files.

Project setup uses `.agents/skills/anchorloop/`. Global setup writes the
selected host's native directory, such as `~/.codex/skills/anchorloop/` or
`~/.gemini/skills/anchorloop/`; OpenCode uses
`~/.config/opencode/skills/anchorloop/`. Every copy renders the skill with a
pinned `npx --yes anchorloop@<version>` runner. The runner packages the Python
source, so it can execute later AnchorLoop commands without a globally
installed `anchor` executable. It never writes `node_modules`, a Python bytecode
cache, or a workflow cache into the project.

For repeatable scripts, choose scope and destination explicitly:

~~~powershell
npx anchorloop install --project --platform codex
npx anchorloop install --global --platform gemini
npx anchorloop install --global --all
npx anchorloop install --global --all --preview
~~~

For a project-scoped installation, AnchorLoop rejects symlink and Windows
reparse-point components in `.codex/`, `.agents/`, `skills/`, and the skill
directory. `--force` can replace only AnchorLoop-owned assets; it never relaxes
this filesystem boundary.

For the standalone Python CLI, explicitly apply a previewed skill installation:

~~~powershell
# Guided terminal setup
anchor install --interactive

# Explicit cross-framework project installation
anchor install --project --platform agents --apply

# Explicit global multi-agent installation
anchor install --global --all --apply
~~~

Without `--project`, the standalone command targets the current user's skill
directory. Use `--global` when you want that scope to be explicit.

The copied package contains:

~~~text
SKILL.md
references/workflow.md
.anchorloop-skill.json
~~~

The marker stores a SHA-256 digest for every installed asset and records the
chosen command runner. By default, install and uninstall stop if an
installer-owned file was edited locally; this preserves local work and prevents
broad deletion. Use `--force` only when those edits are intentionally being
replaced or removed.

Install, update, and uninstall are serialized per destination and use a durable
journal outside the project. The marker is committed last. If a process stops
between asset writes, the next mutating installer command rolls the exact
operation forward before proceeding; read-only status reports
`recovery_pending` without changing files. A successful operation removes its
journal and does not leave a cache in the repository.

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

The installed skill directs an agent to run the installer-rendered command
runner (either `anchor` or a pinned npx command) for `status`, then read
`.anchor/next-action.md`. It must not edit state JSON directly or act as the
engineer at approval, rule, verification, or close gates.

The skill also enforces the human-ownership modes exposed by the CLI. It uses
`AUTO` risk selection, asks for real engineer-authored plan/artifact and
comprehension inputs in STANDARD/CAREFUL, requires rollback mitigation for
CAREFUL, and never fabricates immediate or delayed recall. Project lock,
transaction, outbox, cache, npm-cache, and bytecode artifacts remain ignored
runtime state rather than committed evidence.

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
