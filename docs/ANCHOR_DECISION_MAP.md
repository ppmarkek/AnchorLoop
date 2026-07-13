# AnchorLoop decision map

This compact map records decisions that need a deliberate answer before public beta. The plan uses the stated default where possible.

## #1: First distribution target

Blocked by: none  
Type: Discuss

### Question

Should the first public release target only Codex, or support several coding agents from day one?

### Answer

Pending. Default: Codex-first skill and local CLI with an adapter interface that does not lock out other agents.

## #2: CLI runtime

Blocked by: #1  
Type: Prototype

### Question

Should `anchor` use TypeScript/Node, Python, or a compiled runtime?

### Answer

Pending. Prototype bootstrap, YAML/JSON state, subprocess calls, and cross-platform install first. The runtime must not decide the workflow model.

## #3: Skill catalogue and trust policy

Blocked by: #1  
Type: Research

### Question

Which sources may `anchor skills find` search, how are candidates ranked, and what is required before installation?

### Answer

Pending. Default: local skills first, then allowlisted public registries and GitHub; show source, version, license when known, and an install preview. Never auto-install.

## #4: Network and privacy policy

Blocked by: #3  
Type: Discuss

### Question

What leaves the developer machine for research and skill discovery?

### Answer

Pending. Default: source code, briefs, task history, and learning history remain local. External research sends only an engineer-approved query.

## #5: Versioning project state

Blocked by: none  
Type: Discuss

### Question

Which `.anchor/` artifacts should be committed for a team, and which remain private?

### Answer

Pending. Default: commit workflows, policies, and task contracts; ignore cache, raw logs, research cache, and individual learning records.

## #6: Graph map lifecycle

Blocked by: #1, #5  
Type: Prototype

### Question

Should `graphify-out/` be committed by default, and how will Anchor avoid stale or recursive indexing?

### Answer

Pending. Default: code-only initial map, incremental updates, `.graphifyignore` excluding `.anchor/` and generated directories, then an explicit commit choice.

## #7: Learning retention

Blocked by: #5  
Type: Discuss

### Question

Which learning signals are useful enough to retain without turning Anchor into an intrusive tutor?

### Answer

Pending. Default: learning is opt-in; only an engineer-requested note or delayed recall result is stored locally.

## #8: Quality and security tool profiles

Blocked by: #2, #4
Type: Prototype

### Question

Which language/framework-specific linters, formatters, type checkers, secret scanners, dependency checks, and security rules should `anchor precommit` run without creating a noisy or non-reproducible gate?

### Answer

Pending. Default: run configured project commands plus a diff-based clean-code and security review. Detect Python, JavaScript/TypeScript, and Go to load framework-appropriate guidance; use generic, transparent checks for unsupported stacks. Every tool and network call is visible in the pre-commit result.

## #9: Rule governance and structure policy

Blocked by: #5, #8  
Type: Discuss

### Question

How should a new project approve its initial code-quality, security, and structure policy without making setup onerous, and which structure fields are universal rather than stack-specific?

### Answer

Pending. Default: setup creates reviewable baseline policy packs as proposals, not active rules. The engineer approves one or more exact versions. Later additions, edits, and retirements use the same proposal/approval log; active rules never change silently.
