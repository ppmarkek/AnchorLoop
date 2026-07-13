# AnchorLoop — detailed project plan

Status: draft 0.1  
Scope: agent-neutral, local workflow controller for AI-assisted engineering

## 1. Product intent

AnchorLoop keeps an engineer in control of a software project while an AI agent handles mechanical coding work. It does not measure human-written lines. It protects ownership of:

1. task intent and boundaries;
2. high-impact technical decisions;
3. selected tools and skills;
4. acceptance of delivered behaviour; and
5. the ability to explain or safely debug the change.

> The agent may write the code; the engineer owns why it exists, which trade-off was chosen, and how it is verified.

## 2. Goals

The first release must:

- make the task lifecycle explicit and command-driven;
- stop code changes at human gates;
- persist tasks, workflows, decisions, evidence, and skill policy locally;
- use Graphify before broad file search;
- let the engineer discover, inspect, select, and explicitly install skills;
- offer opt-in explanations and practice tied to the active task;
- work in one repository without a server, account, IDE extension, or remote database;
- give every coding agent access to the same core workflow through the `anchor` CLI and portable project state, while using native integrations when a host supports them.

It explicitly does not:

- demand human-written LOC;
- autonomously prioritise tasks, merge, or deploy;
- upload source code to a central knowledge base;
- install arbitrary packages or skills without preview and approval;
- replace existing tests, linters, security tools, or code review;
- build a dashboard, IDE extension, or multi-agent platform before the core workflow is proven.

## 3. Product shape

AnchorLoop has three layers. The core is independent of any AI provider or IDE.

~~~mermaid
flowchart LR
  E[Engineer] --> H[Agent host / terminal]
  H --> D[Host adapter or generic protocol]
  D --> C[Anchor core CLI & state machine]
  C --> F[.anchor/ project state]
  C --> G[Graphify adapter]
  C --> K[Skill policy & catalogue]
  C --> R[Research adapter]
  H --> A[AI coding agent]
  A --> W[Repository & automated checks]
  E -->|explicit gates| C
~~~

### 3.1 Portable Anchor protocol

The portable protocol defines commands, task states, output formats, approval records, and exit codes. It lives in the CLI and `.anchor/`, so it is not owned by any model, provider, IDE, or slash-command format. A host with terminal access can run `anchor help`, `anchor status`, and every task transition directly. If a host has no terminal integration, the engineer or a local bridge runs the same CLI and supplies the generated next action to the agent.

### 3.2 Local CLI and core

The `anchor` CLI is the source of truth. It creates and validates state, runs deterministic checks, invokes Graphify, performs safe scaffolding, and provides a stable terminal interface. It never decides product intent for the engineer.

### 3.3 Host adapters

A host adapter is deliberately thin. It reads the CLI state and maps the portable protocol to the host’s available surface:

| Host capability | Adapter behaviour |
|---|---|
| No terminal, plugins, or hooks | Read a generated portable instruction/next-action file; the engineer or local bridge executes CLI transitions. No hard enforcement claim. |
| Terminal only | Use `anchor` CLI commands and write the next allowed action to a portable instruction file. |
| Instructions or skills | Install a concise wrapper that reads Anchor state before acting and displays the next gate. |
| Native slash commands | Map the host’s command syntax to `anchor` CLI operations. |
| Hooks | Warn or block edits/commits that violate the active task state, without replacing CLI validation. |
| MCP | Expose structured read-only state and explicit transition tools. |

Every host has the portable-protocol fallback; terminal access makes it self-service. Native integration improves ergonomics and enforcement; it never changes the workflow semantics.

### 3.4 Local-first state

Human-authored configuration and workflows use YAML. Generated records and cache use JSON/JSONL. All state must remain readable and repairable without AI.

## 4. Invariants

1. A task cannot enter implementation until an engineer explicitly approves its plan.
2. A changed task cannot proceed to human verification until it has pre-commit quality evidence; every blocking finding must be fixed or have an explicit, recorded engineer exception.
3. A task cannot close until it has automated evidence and a human verification result; the engineer may mark human verification not applicable only with a reason.
4. The agent may recommend a mode, workflow, skill, or solution but may not select, install, or approve one itself.
5. Learning commands may inspect context but never edit code or advance a task.
6. External research may not send repository content, task history, or learning history without explicit approval.
7. Generated cache never overrides a human-authored workflow, policy, or task record.
8. A missing Graphify graph is reported as a fallback condition, never silently replaced with a claim that the graph was used.
9. An Anchor-supplied quality, security, or structure rule is a proposal until the engineer approves its exact version. A later rule revision does not silently replace the active rule.

Use the definitions in [CONTEXT.md](../CONTEXT.md).

## 5. Roles

| Role | Owns | Does not delegate |
|---|---|---|
| Engineer | intent, scope, priority, mode, decisions, skills, acceptance | final technical and product responsibility |
| Agent | exploration, implementation, repetitive edits, automated checks, concise explanation | gates, closure, skill installation |
| Anchor | state validation, records, command routing, deterministic adapters | decisions on behalf of the engineer |

The first release assumes one engineer. Team support means shared repository state, not hosted user management.

## 6. Commands

Chat uses `/anchor …`. The terminal equivalent is `anchor …` where deterministic execution is needed.

The slash form is an adapter convenience, not a requirement. On an agent that does not provide slash commands, the engineer invokes the equivalent CLI command or writes the command in the host’s supported chat syntax.

### 6.1 Project commands

| Command | Purpose | Mutation policy |
|---|---|---|
| `/anchor help` | Show commands and the exact next input format. | Read-only |
| `/anchor init <name>` | Start a new empty project under Anchor. It does not choose an application framework until the engineer approves a project brief. | Preview, then explicit setup approval |
| `/anchor add` | Attach Anchor to an existing repository. Detects stack and proposes changes but does not alter application source. | Preview, then explicit setup approval |
| `/anchor status` | Show project configuration, active task, graph freshness, mode, and selected skills. | Read-only |
| `/anchor doctor` | Validate CLI, state schema, Graphify, and configured repository commands. | Cache-only |
| `/anchor agent detect` | Detect the current host’s available integration capabilities; no installation. | Read-only |
| `/anchor agent setup <host>` | Preview the selected host adapter, generated instruction files, hooks, and required dependencies. | Preview, then explicit approval |
| `/anchor agent status` | Show generic fallback availability and the active host adapter’s capability matrix. | Read-only |

### 6.2 Task commands

| Command | Valid state | Outcome |
|---|---|---|
| `/anchor start "title"` | no active task | Create task and request brief |
| `/anchor plan` | briefing complete | Inspect relevant code, recommend mode, propose plan; no edits |
| `/anchor approve` | plan proposed | Record approved plan and required human artifact |
| `/anchor implement` | approved | Allow smallest coherent patch and automated checks |
| `/anchor review` | implementation complete | Present evidence, decision, risk, and manual scenario |
| `/anchor precommit` | review ready | Run configured tests plus clean-code and security gate; it never creates a commit |
| `/anchor verify` | pre-commit passed or exception recorded | Record engineer result: pass, fail, partial, or N/A with reason |
| `/anchor close` | verification recorded | Enforce closure criteria and archive |
| `/anchor pause`, `resume` | any non-closed task | Preserve and restore explicit state |
| `/anchor tasks` | any | List task records |

### 6.3 Discovery and research

| Command | Outcome | Output limit |
|---|---|---|
| `/anchor locate "question"` | Query Graphify then use `rg` only when necessary; identify relevant paths and symbols. | 5 paths with reasons |
| `/anchor map build` | Build a code-only Graphify map after approval. | Run summary |
| `/anchor map update` | Incrementally refresh a graph. | Delta summary |
| `/anchor research "problem"` | Find cited external approaches; does not select one or edit code. | 3–5 approaches |
| `/anchor research choose N` | Record the engineer-selected approach in the task. | Confirmation |

### 6.4 Skill control

| Command | Outcome |
|---|---|
| `/anchor skills find "task or capability"` | Return exactly ten candidate skills, ranked but not selected. |
| `/anchor skills inspect N` | Show source, purpose, trigger, files, permissions, dependencies, version/license when known, and risk. |
| `/anchor skills select 2 7` | Select skills only for the active task. |
| `/anchor skills install N` | Show exact install plan; wait for approval. |
| `/anchor skills allow <name>` / `deny <name>` | Update project policy. |
| `/anchor skills list` | Show installed, allowed, denied, and task-selected skills. |

Anchor manages third-party and project skills. It can document but cannot disable host-enforced system or safety capabilities.

### 6.5 Rules and project structure

| Command | Outcome |
|---|---|
| `/anchor rules list` | Show active, proposed, rejected, and retired rules with version and approval evidence. |
| `/anchor rules propose <category> "rule"` | Create a reviewable quality, security, or structure-rule proposal; it has no effect. |
| `/anchor rules inspect <id>` | Show exact wording, scope, rationale, examples, affected checks, and differences from the active version. |
| `/anchor rules approve <id>` | Activate one exact proposed version after the engineer reviews it. |
| `/anchor rules reject <id>` / `retire <id>` | Preserve the decision and reason without silently deleting history. |
| `/anchor structure show` | Show the active structure policy and current compliance summary. |
| `/anchor structure propose "outcome"` | Map current impact with Graphify and propose a structural change without editing files. |
| `/anchor structure approve <id>` | Record approval of the structural plan; new rule proposals still need their own approval. |
| `/anchor structure apply <id>` | Apply an approved structural plan only while the task is in implementation. |
| `/anchor structure check` | Check the current diff against only the active, approved structure policy. |

### 6.6 Learning

| Command | Outcome |
|---|---|
| `/anchor learn explain "question" [--deep]` | Explain a concept in the current task context. |
| `/anchor learn decision` | Explain the recorded or proposed technical decision and rejected option. |
| `/anchor learn trace "scenario"` | Trace real execution flow with Graphify nodes and source locations. |
| `/anchor learn practice "topic"` | Give a small exercise without revealing the solution first. |
| `/anchor learn check "my explanation"` | Compare engineer explanation with task evidence. |
| `/anchor learn recall` | Run delayed recall without first showing the prior diff or answer. |

## 7. Interaction formats

### 7.1 Help

~~~
ANCHOR: you own scope, decisions, skills, and acceptance.
The agent explores and writes code only after an explicit gate.

Next command:
  /anchor start "short task title"

After that, answer exactly:
Outcome:
Scope / non-goals:
Constraints:
Invariant or acceptance case:
Main uncertainty:
~~~

### 7.2 Brief

The brief is intentionally five lines. A field may be `Unknown`, but must be explicitly marked so.

~~~
Outcome: Retry temporary webhook failures.
Scope / non-goals: Keep public event payload unchanged.
Constraints: No new service or external queue.
Invariant or acceptance case: An event is never acknowledged twice.
Main uncertainty: Where retry state belongs.
~~~

### 7.3 Plan

The agent returns no more than eight lines.

~~~
State: planning
Recommended mode: STANDARD — public behaviour changes, rollback is simple.
Affected: WebhookController, EventHandler, delivery tests.
Approach: Persist retry state beside delivery records.
Alternative: In-memory queue; rejected because restart loses state.
Primary risk: Duplicate acknowledgement after retry.
Proof: unit test for a duplicate event plus integration test for transient 5xx.
Required human artifact: approve the acceptance case or replace it.
~~~

### 7.4 Review

~~~
State: review-ready
Changed: <up to three lines>
Decision: <chosen option and main rejected alternative>
Risk: <most likely remaining failure mode>
Automated verification: <exact command and result>
Human verification: <exact scenario>
Next command: /anchor precommit
~~~

### 7.5 Pre-commit quality gate

~~~
State: pre-commit
Result: PASS | BLOCKED | ENGINEER DECISION REQUIRED
Automated checks: <format, lint, type check, tests and results>
Clean-code review: <only concrete findings, or "no material finding">
Security review: <only concrete findings, or "no material finding">
Required action: <exact correction, accepted exception, or "none">
Commit: not created; engineer uses the normal Git workflow after PASS.
~~~

The result must separate objective command failures from advisory design findings. It may not call a rule violation merely because a principle can be named.

### 7.6 Skill candidates

Every result follows the same compact format.

~~~
1. graphify
   Overview: project knowledge graph for scoped code navigation.
   Fit: locate connected modules before a cross-cutting change.
   Source: https://github.com/Graphify-Labs/graphify
   Cost/risk: local AST pass; documents/media may use model or API capacity.
~~~

## 8. Modes

| Mode | Choose when | Before implementation | Before closure |
|---|---|---|---|
| `FAST` | Familiar and low/reversible risk | Plan approval | Automated evidence and human result, unless N/A |
| `STANDARD` | Novelty or meaningful risk | Plan plus one human artifact | Verification plus one concise prediction/explanation |
| `CAREFUL` | High novelty and risk, or a risk rule matches | Plan, human artifact, explicit decision, rollback/mitigation | Verification, comprehension check, delayed recall scheduled |

Initial risk rules flag migrations, auth, authorization, payments, secrets, public APIs, concurrency, cryptography, infrastructure, destructive operations, and new dependencies. Rules recommend `CAREFUL`; the engineer can override with a reason.

## 9. Always-on code standards and pre-commit gate

These are implementation rules, not optional commands once they are active. Setup installs them as reviewable baseline proposals; the engineer must approve the exact policy pack before the agent applies it. `/anchor precommit` makes evidence from the active ruleset visible before the engineer commits.

### 9.1 Clean-code rules

- Name variables, functions, types, modules, and tests by their intent. Prefer `totalAmount` to `s`, and a behaviour-oriented function name to an abbreviation.
- Do not comment what the code visibly does. Comment a non-obvious constraint, trade-off, security boundary, or reason a seemingly simpler option is unsafe.
- Make the smallest coherent patch. Remove dead code, unused imports, abandoned branches, and obsolete comments introduced by the change.
- Refactor nearby code when it simplifies the changed behaviour and remains covered by tests. Do not turn a small task into an unapproved rewrite.
- Keep functions and modules focused enough that their purpose can be described in one short sentence.

### 9.2 Principles as evidence, not dogma

| Principle | Gate question | Do not misuse it to |
|---|---|---|
| DRY | Is the same domain rule or change-prone knowledge duplicated in two places? | Extract a three-line coincidence into a premature abstraction. |
| KISS | Is there a simpler, understandable design that satisfies the approved brief and risk controls? | Remove required validation, tests, or security controls. |
| YAGNI | Did this change add a flag, layer, dependency, configuration, or extension point without an approved present need? | Prevent a necessary seam for a demonstrated requirement. |
| SOLID | In object-oriented code, does a changed type mix unrelated reasons to change, hide a dependency, or force consumers to depend on unused behaviour? | Invent interfaces, classes, or patterns where a direct function is clearer. |

The review reports a principle only with a concrete diff location, likely maintenance or correctness cost, and a proportionate alternative. It never emits generic “make it more SOLID” advice.

### 9.3 Security baseline

Every changed diff is checked for:

- hard-coded secrets, tokens, credentials, or private keys;
- unsafe handling of external input, output encoding, or unvalidated data crossing a trust boundary;
- authorization checks removed, bypassed, or implemented only on a client;
- unsafe dynamic SQL, shell command, file path, deserialization, redirect, or network request construction;
- accidental sensitive logging or error exposure;
- a changed dependency or lockfile without a recorded reason and compatible security check.

For detected Python, JavaScript/TypeScript, or Go projects, Anchor loads the applicable language/framework security profile and configured security tools. Unsupported stacks receive the generic baseline plus an explicit statement that no framework-specific profile was available. The gate must not report TLS or a secure-cookie setting as a defect without deployment context.

### 9.4 Gate behaviour

1. Run the configured formatter, linter, type checker, unit/integration tests, and safe local security checks.
2. Inspect the staged or task diff against the clean-code and security rules.
3. Classify each result as pass, blocking failure, or engineer decision required.
4. The agent may repair deterministic formatting or test failures that remain within the approved task. It asks the engineer before changing scope, architecture, public behaviour, or accepting a security exception.
5. Run `/anchor structure check` against the active structure policy when a changed path, module boundary, or import relationship is in scope.
6. The command does not run `git commit`. Committing stays in the engineer’s normal Git workflow.

### 9.5 Engineer-approved rule lifecycle

1. `init` or `add` creates baseline quality, security, and structure packs as **proposals**, tailored only from observable project facts.
2. The engineer inspects each pack, then approves, rejects, or edits it. Setup approval alone does not imply approval of unknown future rule versions.
3. Anchor records the active ruleset version in every task at plan approval; the task keeps that version unless the engineer explicitly upgrades it.
4. The agent may propose a rule when a repeated problem appears, but it cannot enforce the rule, update an active version, or retire an old rule.
5. A rule proposal must include: ID, category, exact wording, scope, rationale, examples/non-examples, severity, affected checks, migration impact, and source if it came from outside the project.
6. An emergency security exception is a separate engineer decision with scope, expiry/review date, and mitigation; it is never silently converted into a permanent rule.

### 9.6 Project-structure policy

The structure policy is not a generic folder template. It is an engineer-approved contract that may define:

- source, test, documentation, generated, and infrastructure roots;
- how a module is identified and where its public entry point is;
- allowed import/dependency directions and forbidden cross-module access;
- where domain rules, adapters, UI/transport, configuration, and persistence may live when those concepts exist in the project;
- test placement and what tests are required when a boundary changes;
- when code can enter a shared module and when duplication is preferable to a premature `utils` bucket;
- package/workspace ownership, build-path aliases, and generated-code rules.

The baseline proposal recommends these conservative principles:

1. Organise by meaningful capability or domain boundary where the project has one; do not force a universal layer tree.
2. Keep a module’s externally supported API explicit; other modules depend on it rather than internal files.
3. Direct dependencies toward stable domain/application contracts rather than UI, transport, or infrastructure details where the architecture has those layers.
4. Keep generated code and build artefacts outside hand-maintained source boundaries.
5. Place tests according to the approved project convention and preserve test intent when moving code.
6. Add shared infrastructure only after an actual shared need is demonstrated; do not accumulate unrelated helpers in a catch-all directory.

None of these recommendations become a rule until approved for this project.

### 9.7 Structural-change workflow

A structural change includes moving a source root, splitting/merging modules, changing a module’s public boundary, changing dependency direction, introducing a package/workspace, or changing import/path conventions.

1. The engineer creates or approves a task and runs `/anchor structure propose "outcome"`.
2. The agent queries Graphify, lists impacted modules/imports/tests/build configuration, and produces a no-edit plan with compatibility and rollback strategy.
3. If the plan needs a new or changed structure rule, Anchor creates a separate rule proposal. The engineer approves the plan and each rule change independently.
4. The engineer authorizes implementation. The agent moves code in small verified steps, keeps temporary compatibility shims only when approved, and removes them by an explicit follow-up task.
5. `precommit` runs configured checks, active structure checks, affected tests, and a graph/update impact summary.
6. The engineer performs the defined manual verification before closure.

Structural changes normally recommend `CAREFUL` mode. An engineer may choose another mode only with a recorded reason.

## 10. State machine

~~~mermaid
stateDiagram-v2
  [*] --> briefing
  briefing --> planned: plan
  planned --> approved: approve
  approved --> implementing: implement
  implementing --> review_ready: automated checks complete
  review_ready --> quality_checked: precommit passes or exception recorded
  review_ready --> implementing: blocking finding needs code fix
  quality_checked --> verified: verify
  verified --> closed: close
  briefing --> paused
  planned --> paused
  approved --> paused
  implementing --> paused
  review_ready --> paused
  quality_checked --> paused
  paused --> briefing
  paused --> planned
  paused --> approved
  paused --> implementing
  paused --> review_ready
  paused --> quality_checked
  quality_checked --> implementing: manual verification fails within scope
  quality_checked --> planned: verification changes decision or scope
~~~

A paused task stores its prior state. A transition that changes source files is rejected unless the task is `implementing`.

## 11. Local layout

~~~
.anchor/
  config.yaml                     # committed project settings
  protocol/
    anchor-protocol.yaml           # committed portable commands, states, and output schema
  agents/
    capabilities.json              # detected host capabilities; local cache
    adapters/                      # selected adapter manifests and generated instructions
  workflows/                      # committed state-machine definitions
    feature.yaml
    bugfix.yaml
    refactor.yaml
    migration.yaml
    new-project.yaml
  templates/                      # committed concise response templates
  rules/
    approved/                     # committed immutable rule versions
    proposals/                    # reviewable packs; no effect before approval
      baseline-code-quality-v1.yaml
      baseline-security-v1.yaml
      baseline-structure-v1.yaml
    history.jsonl                 # append-only approvals, rejections, retirements
  architecture/
    structure.yaml                # active, approved structure policy
    proposals/                    # structural plans and impact reports
  tasks/                          # commit policy chosen in setup
    <task-id>.yaml
  skills/
    policy.yaml                   # committed allow/deny rules
    selected.yaml                 # local active selections
    catalogue-cache.json          # ignored
  graphify/
    integration.yaml              # committed adapter config
    query-history.jsonl           # ignored
  learning/
    notes/                        # local unless explicitly exported
    recall.jsonl                  # local
  cache/                          # ignored
  logs/                           # ignored

.agents/skills/graphify/          # project Graphify skill
.graphifyignore                   # source-index exclusions
graphify-out/                     # Graphify artefact; commit policy chosen in setup
~~~

The setup must not silently ignore task contracts when a team selects shared state.

### 11.1 Task schema

~~~yaml
id: al-20260713-001
title: Retry temporary webhook failures
workflow: feature
mode: standard
state: planned
brief:
  outcome: Retry temporary webhook failures.
  scope: Keep public event payload unchanged.
  constraints: No new service or external queue.
  invariant: An event is never acknowledged twice.
  uncertainty: Where retry state belongs.
plan:
  summary: Persist retry state beside delivery records.
  alternative: In-memory retry queue.
  risk: Duplicate acknowledgement after retry.
  verification: delivery unit and integration tests.
human_artifact: {}
decisions: []
selected_skills: []
ruleset_version: approved-baseline-v1
evidence:
  automated: []
  quality:
    status: pending
    commands: []
    findings: []
    exceptions: []
  structure:
    policy_version: approved-baseline-v1
    checks: []
    impact_summary: null
  manual: null
learning:
  recall_due_at: null
~~~

The CLI validates every write and preserves an append-only transition event log.

## 12. Graphify adapter

Graphify is the first navigation provider, not a replacement for source control or tests. Anchor calls its CLI from the agent-neutral core and uses a host-specific Graphify skill only when the host supports skills. Its upstream project supports project-scoped agent installation, `graphify-out/`, `.graphifyignore`, and incremental updates. See [Graphify](https://github.com/Graphify-Labs/graphify).

### 12.1 Setup

Before changing anything, `init` and `add` show:

~~~
Will create: .anchor/, .graphifyignore, Graphify integration configuration.
Will install: Graphify CLI and project-scoped Graphify skill.
Will index: source code only; generated and private Anchor files are excluded.
Will not modify: application source code or application dependencies.
Approval required: /anchor approve setup
~~~

After approval Anchor records the upstream Graphify version, creates ignore rules, registers the project skill, and builds a code-only map. Semantic document/media extraction is opt-in because it can consume model/API capacity.

### 12.2 Locate algorithm

1. Check whether a graph exists and whether it is stale.
2. Update it incrementally only when needed; warn when the update could be expensive.
3. Query the graph with the current task question.
4. Return at most five files/symbols with source locations and reasons.
5. Fall back to `rg`, then targeted reads, only when coverage is inadequate.
6. Record a local hit/fallback outcome to measure whether the graph reduces exploration.

## 13. Research and solution selection

Research must separate discovery from decision.

1. Restate the question and offer the engineer a chance to remove private terms.
2. Search primary sources first: official docs, standards, library maintainers, and original repositories.
3. Return three to five feasible approaches, including source links, compatibility, trade-offs, effort, and risks.
4. Mark sourced facts separately from inferences.
5. Wait for `/anchor research choose N` or an engineer-written alternative before changing the task plan.

The adapter needs a no-network mode. Every response states whether network access occurred.

## 14. Skill catalogue and installation guard

### 14.1 Candidate sources

Search in this order:

1. already installed local and project skills;
2. configured curated registries;
3. allowlisted GitHub repositories;
4. broad public search only when the engineer enables it.

Rank by task fit, platform compatibility, maintenance signal, license, installation risk, and existing local capability. Ranking is never approval.

### 14.2 Install preview

Before installation show source URL, pinned revision/version, files to add/change, dependencies, executable scripts, network calls, permissions, and policy result. Require a separate confirmation. Record the selected version in task history and the policy.

### 14.3 Scope

Task selection does not make a skill global, enable network access, or overwrite project instructions. Permanent adoption uses `skills allow`.

## 15. Learning loop

Learning is a service to the current work, not a compulsory quiz system.

Every explanation contains:

1. the concept in plain language;
2. where it appears in the active task, with files/symbols when known;
3. one relevant invariant or likely failure mode; and
4. at most one optional question or exercise.

Default output is short. `--deep` can add trace, comparison, and example. The agent distinguishes code evidence from inference and does not explain the whole codebase by default.

`practice` asks for a prediction, test, or small modification before revealing an answer. `recall` is scheduled only for `CAREFUL` by default. Learning records stay local unless the engineer exports them.

## 16. Security, privacy, and failure policy

- Keep source, task, graph, and learning data local by default.
- Exclude secrets, environment files, dependency directories, build outputs, and `.anchor/cache/` from Graphify.
- Never execute a discovered skill's command outside the normal approval boundary.
- Show every external URL, package, and install command before execution.
- Treat a found secret, an authorization bypass, injection-risk dynamic execution, or unsafe deserialization as a blocking pre-commit finding until resolved or explicitly accepted by the engineer with a recorded reason.
- Run security tooling locally by default. A command that requires network access, such as a dependency advisory lookup, must declare that fact before it runs.
- Audit state transitions, approvals, installations, and verification while omitting secrets and environment values.
- On corrupt state, switch to read-only `doctor` mode; never invent an approval.
- On Graphify failure, report a direct-search fallback.
- Make metric collection diagnostic only, never an individual performance score.

## 17. Milestones

### M0 — contract and schemas

Deliver:

- portable Anchor protocol plus a thin reference adapter for a skill-capable host;
- workflow schemas for feature, bugfix, refactor, migration, and new project;
- task/state schema, transition table, and output fixtures;
- proposed quality, security, and structure baseline packs, rule-governance schema, and quality result schema;
- glossary and decision map.

Done when every command has a state, allowed actions, required human input, and persisted record; no proposed rule can affect a task until approval.

### M1 — bootstrap and help

Deliver:

- `init`, `add`, `help`, `status`, and `doctor`;
- `agent detect`, `agent setup`, and `agent status` with a terminal-only fallback;
- setup preview/approval protocol;
- default `.anchor/` scaffold and ignore files;
- tests for empty, non-empty, non-git, and already-initialised directories.

Done when setup is idempotent, source code remains untouched by `add`, interrupted setup can recover, and `help` gives one copyable next action.

### M2 — task workflow

Deliver:

- `start`, `plan`, `approve`, `implement`, `review`, `precommit`, `verify`, `close`, `pause`, `resume`, and `tasks`;
- rule proposal/approval history, structural-plan proposal/approval, and structure-policy checks;
- state validation and append-only transition log;
- mode recommendation with engineer override;
- configured test/lint/type-check execution, diff quality review, and baseline security review;
- readable task summaries.

Done when invalid transitions fail clearly, approvals survive a new chat session, a blocking quality result prevents verification, failed verification returns to planning without losing evidence, and records can be read without the CLI.

### M3 — Graphify navigation

Deliver:

- Graphify install/version/check adapter;
- `.graphifyignore` generator;
- map build/update, locate, freshness detection, and `rg` fallback;
- time, token, and hit-quality instrumentation.

Done when code-only mapping works after approval, locate uses a fresh graph when present, generated files are excluded, and fallback is transparent.

### M4 — research and skill control

Deliver:

- primary-source research adapter and no-network mode;
- catalogue interface, local cache, inspect, selection, policy, and installation preview;
- exactly-ten candidate result format;
- audit entries for selection and installation.

Done when no skill can install without approval, task selection cannot alter global policy, every candidate has a link and overview, and unsafe/unavailable candidates are marked.

### M5 — learning loop

Deliver:

- explain, decision, trace, practice, check, and recall commands;
- Graphify source-location integration;
- local learning cache with export/forget controls;
- no-edit/no-state-change guarantees.

Done when learning cannot change source or state, every explanation has evidence and a failure mode, practice hides answers until attempted, and recall hides the old answer first.

### M6 — two-week pilot

Use real feature, bugfix, and refactor tasks. Compare usual work with AnchorLoop within task type.

Record:

~~~
Task type and mode
Active human minutes
Wall-clock minutes
Agent turns and token use
Graphify hit/fallback outcome
Selected skills and installation count
Automated and human verification result
Rework, rollback, or defect after closure
24-hour comprehension score
~~~

Set success thresholds before the pilot. Initial target: no more than 5% worse wall-clock time, lower or equal rework, fewer irrelevant reads/agent turns, and better delayed understanding for `STANDARD` and `CAREFUL` tasks.

### M7 — public beta decision

Only after pilot evidence:

- tune defaults from observed friction;
- publish a compatibility matrix and promote generic host support to native adapters where it materially improves control;
- choose the long-term CLI runtime/installer;
- publish worked examples;
- decide the default commit policy for task state and `graphify-out/`.

## 18. Tests

| Layer | Required coverage |
|---|---|
| Workflow engine | valid/invalid transitions, approval gates, pause/resume, migration between workflow versions |
| State files | schema validation, atomic writes, corruption recovery, upgrades, ignore policy |
| CLI | parsing, preview/approve behaviour, exit codes, non-interactive operation |
| Portable protocol | CLI fixtures for help, planning, approval, review, failed verification, learning, and skill selection |
| Host adapters | no-terminal and terminal-only fallback, capability detection, generated instruction wrappers, native-command mapping, and hook absence |
| Quality gate | configured command failures, clean-code finding evidence, exception recording, no-commit guarantee |
| Security | secret detection, injection/authz boundary fixtures, language-profile loading, network declaration |
| Rule governance | proposed rules cannot apply, exact-version approval, edit/retire audit trail, task ruleset pinning |
| Structure policy | allowed/forbidden dependencies, public-boundary checks, source-root moves, generated-code exclusion, approved migration plans |
| Graphify adapter | absent CLI, install failure, fresh/stale graph, ignore rules, query, fallback |
| Research/skills | no-network mode, source attribution, exactly ten results, unsafe installation rejection |
| End-to-end | fixture repo from add through close, with a new chat/session at every state |

Tests assert state, permitted actions, evidence, and command structure—not that a model wrote attractive prose.

## 19. Metrics

### Ownership and safety

- implementation attempts correctly blocked before approval;
- closed tasks with human verification;
- `STANDARD`/ `CAREFUL` tasks with human artifact;
- skills installed via preview and approval.
- pre-commit gates passed, blocked, and overridden by category.
- rule proposals approved, rejected, or superseded; structural-rule violations by category.

### Efficiency

- files read and tokens used before a plan;
- Graphify hit and fallback rate;
- agent turns, wall-clock time, and rework by mode;
- incremental map update time.

### Learning

- opt-in learning usage;
- practice completion;
- delayed recall score;
- developer-reported usefulness.

Metrics diagnose the workflow; they never rank individual engineers.

## 20. Risks

| Risk | Mitigation |
|---|---|
| Workflow feels bureaucratic | Keep FAST short; measure abandonment and friction in the pilot. |
| Agent ignores the workflow in free chat | Skill reads state first; CLI validates state independently. |
| Graphify is slow or costly | Code-only local map by default, ignores, incremental updates, transparent fallback. |
| Graph is stale or inaccurate | Show freshness/confidence, cite source, fall back to source search. |
| Skill search creates supply-chain risk | Trust policy, inspection, pinned revision, no auto-execution. |
| Learning becomes noise | Fully opt-in, concise, task-specific, no blocking in FAST. |
| Quality rules become style policing | Require concrete diff evidence, cost, and proportionate alternative; keep deterministic style in formatters/linters. |
| Security scan becomes noisy or misses context | Load language-specific profiles when available; distinguish findings, uncertain warnings, and accepted exceptions. |
| AI silently changes project architecture | Pin ruleset versions, require separate structural-plan and rule approvals, and make structure checks use only approved policy. |
| State exposes context | Local-first storage, ignore defaults, export only by choice. |
| Graphify changes upstream | Adapter boundary, version capture, compatibility tests, graceful degradation. |
| One host imposes its workflow on all others | CLI and `.anchor/` remain the source of truth; adapters are thin and capability-bound. |

## 21. Build order

1. Finalise workflow contract and schemas.
2. Implement the portable command protocol and terminal-only fallback.
3. Implement local scaffold, `init`, `add`, and host-capability detection.
4. Build rule governance, project-structure policy, task lifecycle, and quality/security gate end-to-end in a fixture repository.
5. Add Graphify and `locate`, then structural impact analysis.
6. Add learning commands.
7. Add external research and skill discovery/control.
8. Run the pilot across at least two different agent hosts; add native adapters based on observed capability gaps rather than provider preference.

## 22. Open decisions

Before work beyond M1, resolve the frontier in [ANCHOR_DECISION_MAP.md](ANCHOR_DECISION_MAP.md): distribution target, runtime, skill-catalogue trust policy, network/privacy, state versioning, Graphify lifecycle, learning retention, quality/security tool profiles, and rule-governance defaults.
