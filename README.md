# AnchorLoop

**Engineer-controlled, agent-neutral workflow for AI-assisted software delivery.**

[English](README.md) · [Русский](docs/i18n/README.ru.md) · [Español](docs/i18n/README.es.md) · [Português](docs/i18n/README.pt-BR.md) · [Français](docs/i18n/README.fr.md) · [Deutsch](docs/i18n/README.de.md) · [日本語](docs/i18n/README.ja.md) · [简体中文](docs/i18n/README.zh-CN.md)

AnchorLoop lets an AI agent implement code without taking ownership away from the engineer. The engineer explicitly controls task intent, decisions, project rules, skills, structure changes, and final acceptance.

## Status

Pre-alpha. The first working core is available as a local Python CLI with an optional, installable agent-neutral skill adapter. It creates portable project state, enforces task gates, records rule approval, and provides a small local pre-commit baseline.

## Core idea

> The agent may write the code. The engineer owns why it exists, what trade-off was made, which rules apply, and how the result is verified.

AnchorLoop does not measure human-written lines. It focuses on the work that preserves engineering ownership:

- writing the task outcome and constraints;
- approving the plan before implementation;
- approving new quality, security, and structure rules;
- selecting skills and external solutions;
- checking the delivered behaviour;
- learning when a concept or decision is unclear.

## Trust boundary

AnchorLoop records an auditable workflow gate; it is not authentication or
access control by itself. A coding agent with access to the same terminal can
invoke CLI commands and supply a name. Approval records therefore include
provenance:

- `audit` records who says they approved an action;
- `interactive-tty` requires an interactive terminal and an explicit typed
  `APPROVE` confirmation;
- a trusted host adapter or separate approval channel remains future work.

Do not treat `--by` or a terminal confirmation as proof of a human identity
without such a trusted approval channel. The portable skill reinforces this
rule but does not replace the CLI or `.anchor/` state.

## Agent-neutral by design

The source of truth is the local `anchor` CLI and the project’s `.anchor/` directory—not a particular model, provider, IDE, or slash-command format.

| Host capability | How AnchorLoop works |
|---|---|
| Terminal access | Run the `anchor` CLI directly. |
| Instructions or skills | A host adapter can read the current state and display the next allowed action. |
| Native commands, hooks, or MCP | An adapter can make the workflow more convenient or add guardrails. |
| No terminal integration | The engineer or a local bridge runs the CLI; the agent reads the generated next action. |

Every host gets the same task states and approval rules. Native integrations must remain thin adapters; they never own the workflow state.

## What works now

- `anchor install` and `anchor uninstall` preview then manage a packaged, project- or user-scoped skill adapter for generic Agent Skills or explicit Codex locations. They never modify the `.anchor/` workflow state.
- Failed verification is preserved and can explicitly return to implementation or planning with `anchor revise`; it no longer strands the active task.
- The quality gate records a deterministic workspace fingerprint. Verification and close are blocked when the checked code changes afterward.
- `anchor init` and `anchor add` preview project setup and require `--apply` before creating files.
- Setup creates portable `.anchor/` state, baseline **proposed** rules, Graphify integration metadata, a portable agent protocol, and a generated next-action file.
- The task flow enforces `start → brief → plan → approve → implement → review → precommit → verify → close`.
- Code cannot move to `implement` until the complete engineer brief, plan summary, named approval, and task ruleset snapshot are recorded. If any pinned artifact changes afterward, the stale approval is archived and the task must be approved again.
- Rules are proposals until an engineer runs `anchor rules approve <id> --by <engineer>`. Replacing an active rule requires an explicit `anchor rules supersede` record; legacy approved rules must be migrated through that explicit path.
- `anchor precommit` always runs Python syntax and Git whitespace checks; a simple secret/key scan runs only when the task's engineer-approved security rule is active.
- `anchor agent detect` and `anchor agent status` are read-only; `anchor agent setup portable` previews then records the portable adapter.

Graphify installation, full language-specific security tooling, project-specific test commands, external research, skill discovery, and native host adapters are planned next. AnchorLoop never installs them silently.

## Install as a command-line tool

Requirements: Python 3.11 or newer. To install the current project directly
from its Git repository, without cloning a development checkout:

~~~sh
pipx install git+https://github.com/ppmarkek/AnchorLoop.git
~~~

If you do not use `pipx`, install it into the active Python environment:

~~~sh
python -m pip install "git+https://github.com/ppmarkek/AnchorLoop.git"
~~~

This is a Git installation path, not a PyPI release. Afterward, run `anchor
install ...` to add the optional portable skill adapter to a project or user
skill directory.

## Development from a checkout

Requirements: Python 3.11 or newer.

~~~sh
git clone https://github.com/ppmarkek/AnchorLoop.git
cd AnchorLoop
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
~~~

On Windows, activate the virtual environment with:

~~~powershell
.venv\Scripts\Activate.ps1
~~~

## Install the portable skill adapter

The CLI remains a standalone, agent-neutral product. Its optional skill package
only tells compatible agents how to consult the CLI and current Anchor state.
It does not replace the workflow engine or make AnchorLoop Codex-only.

After installing the CLI, preview then install the generic project skill:

~~~powershell
anchor install --project --platform agents
anchor install --project --platform agents --apply
~~~

This writes only `.agents/skills/anchorloop/`, which is the cross-framework
Agent Skills location. Codex is an explicit, optional target:

~~~powershell
anchor install --project --platform codex --apply
~~~

The installer copies packaged Markdown and an ownership marker. It does not
modify `.anchor/`, application code, `AGENTS.md`, host hooks, or Graphify
configuration. It refuses to overwrite or remove locally modified skill assets
until the engineer explicitly uses `--force`. Remove only unchanged,
installer-owned files with:

~~~powershell
anchor uninstall --project --platform agents --apply
~~~

## First project

From the repository you want to control:

~~~sh
anchor add
anchor add --apply
anchor rules list
anchor rules approve baseline-code-quality-v1 --by "Ada Engineer"
anchor rules approve baseline-security-v1 --by "Ada Engineer"
anchor rules approve baseline-structure-v1 --by "Ada Engineer"
anchor start "Retry temporary webhook failures"
anchor brief --by "Ada Engineer" --outcome "Retry temporary failures" --scope "Webhook delivery only" --constraints "Keep the API compatible" --invariant "A transient failure retries safely" --uncertainty "Provider retry limits"
~~~

The first command only prints the setup plan. The second creates state. Nothing is installed, indexed, committed, or changed in application source code without an explicit command.

After starting a task, AnchorLoop asks the engineer for:

~~~text
Outcome:
Scope / non-goals:
Constraints:
Invariant or acceptance case:
Main uncertainty:
~~~

Then progress deliberately:

~~~sh
anchor plan --summary "Use bounded exponential backoff and preserve delivery idempotency."
anchor approve --by "Ada Engineer"
anchor implement
anchor review
anchor precommit
anchor verify --by "Ada Engineer" --result pass --reason "The documented manual scenario passed."
anchor close
~~~

If manual verification fails, preserve that evidence and return through an
explicit revision rather than abandoning the active task:

~~~sh
anchor verify --by "Ada Engineer" --result fail --reason "The retry still loses the delivery id."
anchor revise --target implement --reason "Fix the observed behavior within the approved scope."
~~~

Use `--target plan` when the solution or scope decision must change; then
record a revised plan and approval before implementation resumes.

## Rules belong to the engineer

AnchorLoop proposes baseline rules for code quality, security, and project structure. They are inactive until approved. A rule has an ID, exact wording, category, source, rationale, version, and approval event.

~~~sh
anchor rules list
anchor rules propose structure "Features may import only public module entry points."
anchor rules approve rule-structure-<id> --by "Ada Engineer"
~~~

The active ruleset is pinned to a task when its plan is approved. An agent can propose a new rule but cannot activate, revise, retire, or silently bypass one.

## Pre-commit baseline

Before verification, run:

~~~sh
anchor precommit
~~~

The current baseline blocks:

- invalid Python syntax;
- likely hard-coded credentials or private keys in supported text files, when the task's approved security rule enables that check;
- whitespace errors reported by `git diff --check` and `git diff --cached --check`.

It also records that project-specific formatter, linter, type-checker, test-runner, dependency scanner, and framework security profile still need explicit configuration. This command never creates a Git commit.

Each successful run stores a SHA-256 fingerprint of the checked workspace. If
the tracked diff, staged diff, untracked files, or Git HEAD change before
verification or close, AnchorLoop returns the task to review and requires a new
pre-commit run.

DRY, KISS, YAGNI, SOLID, clean-code, and structural checks are evidence-based policies: a finding must point to a concrete location, explain the likely cost, and propose a proportionate alternative. AnchorLoop must not turn those principles into generic style policing.

## Project state

~~~text
.anchor/
  config.json
  next-action.md
  protocol/                 portable workflow contract
  tasks/                    active and closed task records
  rules/                    proposals, approved versions, active rules
  architecture/             structure proposals and policy
  graphify/                 integration metadata
  agents/                   detected capabilities and adapter manifests
  cache/ and logs/          ignored local artefacts
~~~

The files are deliberately readable. The CLI validates changes but does not hide decisions in a remote service or model memory.

## Documentation

- [Product plan](docs/PROJECT_PLAN.md)
- [Decision map](docs/ANCHOR_DECISION_MAP.md)
- [Domain glossary](CONTEXT.md)
- [Portable skill adapter](docs/PORTABLE_SKILL.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Development

Run the test suite without installing the package:

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests
~~~

Or install the project in editable mode and use:

~~~sh
python3 -m unittest discover -s tests
anchor help
~~~

## License

MIT. See [LICENSE](LICENSE).
