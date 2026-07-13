from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .quality import run_precommit, workspace_fingerprint
from .safe_fs import AnchorError, SafeProjectFS


TASK_TRANSITIONS = {
    "implement": {"approved": "implementing"},
    "review": {"implementing": "review_ready"},
    "precommit": {"review_ready": "quality_checked"},
    "close": {"verified": "closed"},
}

RULE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
APPROVAL_PROVENANCE = {"audit", "interactive-tty"}
RULE_CATEGORIES = {"code-quality", "security", "structure"}


NEXT_ACTIONS = {
    "briefing": "Complete the engineer brief, then run: anchor plan",
    "planned": "Inspect the plan and required human artifact, then run: anchor approve",
    "approved": "Implementation is authorised. Run: anchor implement",
    "implementing": "Make the approved patch and run automated checks, then: anchor review",
    "review_ready": "Review the evidence and run the quality gate: anchor precommit",
    "quality_checked": "Perform the manual verification, then run: anchor verify",
    "verified": "Close the task when the outcome is accepted: anchor close",
}

BASELINE_RULES = (
    (
        "baseline-code-quality-v1",
        "code-quality",
        "Use meaningful names, comments that explain why, small coherent patches, and evidence-based DRY, KISS, YAGNI, and SOLID review.",
    ),
    (
        "baseline-security-v1",
        "security",
        "Check changed code for secrets, trust-boundary mistakes, authorization regressions, injection risks, unsafe dynamic execution, and sensitive logging.",
    ),
    (
        "baseline-structure-v1",
        "structure",
        "Keep source roots, module entry points, dependency directions, generated files, and test placement explicit. Propose structural changes before applying them.",
    ),
)


@dataclass(frozen=True)
class SetupPreview:
    root: Path
    mode: str
    detected_stack: tuple[str, ...]

    def lines(self) -> list[str]:
        return [
            f"Anchor {self.mode} preview for {self.root}",
            "Will create: .anchor/ state, portable protocol, baseline rule proposals, Graphify integration metadata, and .graphifyignore.",
            "Will not: edit application source, install packages, install Graphify, or create a Git commit.",
            "Baseline rules remain inactive until an engineer approves their exact versions.",
            f"Detected project markers: {', '.join(self.detected_stack) or 'none'}.",
            f"From {self.root}, apply with: anchor {self.mode} --apply",
        ]


class AnchorProject:
    """A deep local module for Anchor state, rules, and task transitions."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.fs = SafeProjectFS(self.root)
        self.anchor_dir = self.root / ".anchor"

    @property
    def config_path(self) -> Path:
        return self.anchor_dir / "config.json"

    @property
    def active_task_path(self) -> Path:
        return self.anchor_dir / "tasks" / "active.json"

    @property
    def next_action_path(self) -> Path:
        return self.anchor_dir / "next-action.md"

    @classmethod
    def at(cls, root: str | Path) -> "AnchorProject":
        return cls(Path(root))

    def preview_setup(self, mode: str) -> SetupPreview:
        if mode not in {"init", "add"}:
            raise AnchorError(f"Unknown setup mode: {mode}")
        return SetupPreview(root=self.root, mode=mode, detected_stack=tuple(self._detect_stack()))

    def apply_setup(self, mode: str) -> bool:
        self.preview_setup(mode)
        self.fs.ensure_directory(self.anchor_dir)
        created = not self.fs.exists(self.config_path)

        directories = (
            "protocol",
            "agents/adapters",
            "tasks/closed",
            "rules/proposals",
            "rules/approved",
            "architecture/proposals",
            "graphify",
            "cache",
            "logs",
        )
        for directory in directories:
            self.fs.ensure_directory(self.anchor_dir / directory)

        if created:
            self._write_json(
                self.config_path,
                {
                    "schema_version": 1,
                    "name": self.root.name,
                    "setup_mode": mode,
                    "created_at": self._timestamp(),
                    "detected_stack": self._detect_stack(),
                    "ruleset_version": None,
                    "graphify": {"status": "not-installed", "command": "graphify"},
                },
            )
        protocol_path = self.anchor_dir / "protocol" / "anchor-protocol.json"
        protocol = {
            "version": 2,
            "source_of_truth": "anchor CLI and .anchor state",
            "commands": [
                "brief",
                "plan",
                "approve",
                "revise",
                *sorted(TASK_TRANSITIONS),
                "verify",
            ],
            "states": list(NEXT_ACTIONS),
            "approval_provenance": sorted(APPROVAL_PROVENANCE),
            "quality_evidence": {
                "workspace_fingerprint": "sha256 snapshot of the checked working tree",
                "invalidates_on_change": True,
            },
            "host_adapters": ["portable-instructions", "terminal", "skills", "slash-commands", "hooks", "mcp"],
        }
        try:
            current_protocol = self._read_json(protocol_path) if self.fs.exists(protocol_path) else {}
        except AnchorError:
            current_protocol = {}
        if current_protocol.get("version", 0) < protocol["version"]:
            self._write_json(protocol_path, protocol)
        self._write_text_if_missing(
            self.anchor_dir / "protocol" / "ANCHOR.md",
            "# Anchor protocol\n\n"
            "Read .anchor/next-action.md before proposing or changing code. "
            "Never skip a recorded engineer approval. The anchor CLI is the source of truth.\n",
        )
        self._write_text_if_missing(
            self.anchor_dir / ".gitignore",
            "cache/\nlogs/\ngraphify/query-history.jsonl\n",
        )
        self._write_json_if_missing(
            self.anchor_dir / "graphify" / "integration.json",
            {
                "status": "not-installed",
                "reason": "Graphify installation and project integration require explicit engineer approval.",
                "output": "graphify-out/",
            },
        )
        self._ensure_graphify_ignore()
        for rule_id, category, wording in BASELINE_RULES:
            proposal_path = self._rule_proposal_path(rule_id)
            approved_path = self.anchor_dir / "rules" / "approved" / proposal_path.name
            if not self.fs.exists(proposal_path) and not self.fs.exists(approved_path):
                self._write_json(
                    proposal_path,
                    self._rule_document(rule_id, category, wording, source="AnchorLoop baseline"),
                )
        self._write_json_if_missing(
            self.anchor_dir / "architecture" / "structure-proposal.json",
            {
                "id": "baseline-structure-v1",
                "status": "proposed",
                "message": "Approve the matching structure rule before enforcing a project structure policy.",
            },
        )
        self._append_event({"type": "project.setup" if created else "project.repaired", "mode": mode, "at": self._timestamp()})
        self._write_next_action(self._next_action_for_existing_project())
        return created

    def require_setup(self) -> None:
        if not self.fs.exists(self.config_path):
            raise AnchorError("Anchor is not configured here. Run: anchor add --apply")

    def status(self) -> dict[str, Any]:
        self.require_setup()
        config = self._read_json(self.config_path)
        task = self._read_json(self.active_task_path) if self.fs.exists(self.active_task_path) else None
        return {
            "project": config["name"],
            "root": str(self.root),
            "ruleset_version": config.get("ruleset_version"),
            "active_task": None if task is None else {"id": task["id"], "title": task["title"], "state": task["state"]},
            "next_action": self.next_action(),
        }

    def doctor(self) -> dict[str, Any]:
        checks: list[dict[str, str]] = []
        try:
            configured = self.fs.exists(self.config_path)
        except AnchorError as error:
            return {
                "anchor_configured": False,
                "active_task": False,
                "checks": [
                    {
                        "name": "filesystem-boundary",
                        "status": "failed",
                        "detail": str(error),
                    }
                ],
                "status": "attention",
            }
        if not configured:
            checks.append(
                {
                    "name": "config",
                    "status": "failed",
                    "detail": "Anchor is not configured. Run: anchor add --apply",
                }
            )
        else:
            try:
                config = self._read_json(self.config_path)
                if config.get("schema_version") != 1:
                    checks.append(
                        {
                            "name": "config",
                            "status": "failed",
                            "detail": "Unsupported or missing config schema version.",
                        }
                    )
                else:
                    checks.append({"name": "config", "status": "passed"})
            except AnchorError as error:
                checks.append({"name": "config", "status": "failed", "detail": str(error)})

        if self.fs.exists(self.active_task_path):
            try:
                task = self._read_json(self.active_task_path)
                state = task.get("state")
                if state not in NEXT_ACTIONS:
                    checks.append(
                        {
                            "name": "active-task",
                            "status": "failed",
                            "detail": f"Unknown task state: {state!r}",
                        }
                    )
                else:
                    checks.append({"name": "active-task", "status": "passed"})
            except AnchorError as error:
                checks.append({"name": "active-task", "status": "failed", "detail": str(error)})
        else:
            checks.append({"name": "active-task", "status": "not-run", "detail": "no active task"})

        active_rules = self.anchor_dir / "rules" / "active.json"
        if self.fs.exists(active_rules):
            try:
                rules = self._read_json(active_rules).get("rules", {})
                if not isinstance(rules, dict):
                    raise AnchorError("Active rules must be a JSON object.")
                missing = [
                    rule_id
                    for rule_id in rules.values()
                    if not self.fs.exists(self._rule_approved_path(str(rule_id)))
                ]
                if missing:
                    checks.append(
                        {
                            "name": "active-rules",
                            "status": "failed",
                            "detail": f"Missing approved rule documents: {', '.join(missing)}",
                        }
                    )
                else:
                    self._active_rules_snapshot()
                    checks.append({"name": "active-rules", "status": "passed"})
            except AnchorError as error:
                checks.append({"name": "active-rules", "status": "failed", "detail": str(error)})
        else:
            checks.append({"name": "active-rules", "status": "not-run", "detail": "no active rules"})

        return {
            "anchor_configured": configured,
            "active_task": self.fs.exists(self.active_task_path),
            "checks": checks,
            "status": "ok" if all(check["status"] != "failed" for check in checks) else "attention",
        }

    def start_task(self, title: str) -> dict[str, Any]:
        self.require_setup()
        if self.fs.exists(self.active_task_path):
            task = self._read_json(self.active_task_path)
            raise AnchorError(f"Task {task['id']} is already active in state {task['state']}.")
        normalized_title = title.strip()
        if not normalized_title:
            raise AnchorError("Task title cannot be empty.")
        task = {
            "id": f"al-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid4().hex[:6]}",
            "title": normalized_title,
            "state": "briefing",
            "created_at": self._timestamp(),
            "brief": {
                "outcome": None,
                "scope": None,
                "constraints": None,
                "invariant": None,
                "uncertainty": None,
            },
            "ruleset": None,
            "events": [],
        }
        self._write_json(self.active_task_path, task)
        self._append_task_event(task, "task.started")
        self._write_json(self.active_task_path, task)
        self._write_next_action(
            "Reply with this engineer brief before planning:\n"
            "Outcome:\nScope / non-goals:\nConstraints:\nInvariant or acceptance case:\nMain uncertainty:\n"
            "Record it with: anchor brief --by <engineer> --outcome <text> --scope <text> "
            "--constraints <text> --invariant <text> --uncertainty <text>\n"
        )
        return task

    def record_brief(self, *, by: str, values: dict[str, str]) -> dict[str, Any]:
        task = self._task_in_state("briefing", "brief")
        engineer = self._required_text(by, "Engineer name")
        missing = [name for name, value in values.items() if not value.strip()]
        if missing:
            raise AnchorError(f"Engineer brief is incomplete: {', '.join(missing)}.")
        task["brief"] = {name: value.strip() for name, value in values.items()}
        task["brief_record"] = {
            "by": engineer,
            "at": self._timestamp(),
            "brief_digest": self._document_digest(task["brief"]),
        }
        self._append_task_event(task, "task.brief.recorded")
        self._write_json(self.active_task_path, task)
        self._write_next_action("Brief recorded. Prepare a concrete plan, then run: anchor plan --summary <text>\n")
        return task

    def plan_task(self, summary: str) -> dict[str, Any]:
        task = self._task_in_states({"briefing", "planned"}, "plan")
        brief_record = task.get("brief_record")
        if (
            any(not value for value in task["brief"].values())
            or not isinstance(brief_record, dict)
            or brief_record.get("brief_digest") != self._document_digest(task["brief"])
        ):
            raise AnchorError("Record the complete engineer brief before planning.")
        if "plan" in task:
            task.setdefault("plan_history", []).append(task["plan"])
        task["plan"] = {"summary": self._required_text(summary, "Plan summary"), "at": self._timestamp()}
        return self._advance_task(task, "plan", "planned")

    def approve_task(
        self,
        by: str,
        *,
        provenance: str = "audit",
        interactive_confirmed: bool = False,
    ) -> dict[str, Any]:
        task = self._task_in_state("planned", "approve")
        if "plan" not in task:
            raise AnchorError("A recorded plan is required before approval.")
        snapshot = self._active_rules_snapshot()
        task["ruleset"] = snapshot
        approval_subject = self._task_approval_subject(task)
        task["approval"] = {
            **self._approval_record(by, provenance, interactive_confirmed=interactive_confirmed),
            "plan_summary": task["plan"]["summary"],
            **self._task_approval_digests(approval_subject),
            "ruleset_version": snapshot["version"],
        }
        return self._advance_task(task, "approve", "approved")

    def verify_task(
        self,
        *,
        by: str,
        result: str,
        reason: str,
        provenance: str = "audit",
        interactive_confirmed: bool = False,
    ) -> dict[str, Any]:
        task = self._task_in_state("quality_checked", "verify")
        self._ensure_approval_matches_task(task)
        self._ensure_quality_matches_workspace(task)
        verification = {
            **self._approval_record(by, provenance, interactive_confirmed=interactive_confirmed),
            "result": result,
            "reason": self._required_text(reason, "Verification reason"),
        }
        task["verification"] = verification
        if result == "fail":
            self._append_task_event(task, "task.verify.failed")
            self._write_json(self.active_task_path, task)
            self._write_next_action(
                "Verification failed. Return to the smallest valid revision with one of:\n"
                "anchor revise --target implement --reason <text>\n"
                "anchor revise --target plan --reason <text>\n"
            )
            return task
        return self._advance_task(task, "verify", "verified")

    def revise_task(self, *, target: str, reason: str) -> dict[str, Any]:
        task = self._task_in_states({"implementing", "review_ready", "quality_checked"}, "revise")
        self._ensure_approval_matches_task(task)
        normalized_reason = self._required_text(reason, "Revision reason")
        if target not in {"implement", "plan"}:
            raise AnchorError("Revision target must be one of: implement, plan.")

        revision = {
            "at": self._timestamp(),
            "target": target,
            "reason": normalized_reason,
            "previous_state": task["state"],
            "verification": task.get("verification"),
            "quality": task.get("quality", []),
        }
        if target == "plan":
            revision["approval"] = task.get("approval")
            revision["ruleset"] = task.get("ruleset")
            task.setdefault("revisions", []).append(revision)
            for field in ("approval", "ruleset", "quality", "verification"):
                task.pop(field, None)
            task["state"] = "planned"
            self._append_task_event(task, "task.revise.plan")
            self._write_json(self.active_task_path, task)
            self._write_next_action("Revise the plan, then run: anchor plan --summary <text>\n")
            return task

        task.setdefault("revisions", []).append(revision)
        task.pop("verification", None)
        task["state"] = "implementing"
        self._append_task_event(task, "task.revise.implement")
        self._write_json(self.active_task_path, task)
        self._write_next_action(f"{NEXT_ACTIONS['implementing']}\n")
        return task

    def transition(self, action: str) -> dict[str, Any]:
        self.require_setup()
        if not self.fs.exists(self.active_task_path):
            raise AnchorError("No active task. Run: anchor start \"short task title\"")
        task = self._read_json(self.active_task_path)
        state = task["state"]
        expected = TASK_TRANSITIONS.get(action, {})
        if state not in expected:
            allowed = ", ".join(name for name, states in TASK_TRANSITIONS.items() if state in states)
            detail = f" Allowed next command: anchor {allowed}." if allowed else ""
            raise AnchorError(f"Cannot run '{action}' while task is '{state}'.{detail}")
        if action in {"implement", "review", "precommit", "close"}:
            self._ensure_approval_matches_task(task)
        if action == "close":
            verification = task.get("verification", {})
            if verification.get("result") not in {"pass", "partial", "not-applicable"}:
                raise AnchorError("A recorded engineer verification is required before close.")
            self._ensure_quality_matches_workspace(task)
        task["state"] = expected[state]
        self._append_task_event(task, f"task.{action}")
        if action == "close":
            closed_path = self.anchor_dir / "tasks" / "closed" / f"{task['id']}.json"
            self._write_json(closed_path, task)
            self.fs.unlink(self.active_task_path)
            self._write_next_action("No active task. Start the next one with: anchor start \"short task title\"\n")
            return task
        self._write_json(self.active_task_path, task)
        self._write_next_action(f"{NEXT_ACTIONS[task['state']]}\n")
        return task

    def precommit(self) -> dict[str, Any]:
        self.require_setup()
        if not self.fs.exists(self.active_task_path):
            raise AnchorError("No active task. Run: anchor start \"short task title\"")
        task = self._read_json(self.active_task_path)
        if task["state"] != "review_ready":
            raise AnchorError(f"Cannot run 'precommit' while task is '{task['state']}'.")
        self._ensure_approval_matches_task(task)
        ruleset = task.get("ruleset") or {"rules": {}}
        quality = run_precommit(self.root, active_categories=set(ruleset["rules"]))
        task.setdefault("quality", []).append(quality)
        self._write_json(self.active_task_path, task)
        if quality["status"] == "blocked":
            locations = ", ".join(finding["location"] for finding in quality["findings"])
            raise AnchorError(f"Pre-commit is blocked. Fix findings before verification: {locations}")
        return self.transition("precommit")

    def propose_rule(self, category: str, wording: str) -> dict[str, Any]:
        self.require_setup()
        if category not in RULE_CATEGORIES:
            raise AnchorError("Rule category must be one of: code-quality, security, structure.")
        normalized_wording = wording.strip()
        if not normalized_wording:
            raise AnchorError("Rule wording cannot be empty.")
        rule_id = f"rule-{self._slug(category)}-{uuid4().hex[:8]}"
        document = self._rule_document(rule_id, category, normalized_wording, source="Engineer or agent proposal")
        self._write_json(self._rule_proposal_path(rule_id), document)
        self._append_event({"type": "rule.proposed", "rule_id": rule_id, "at": self._timestamp()})
        return document

    def approve_rule(
        self,
        rule_id: str,
        *,
        by: str,
        provenance: str = "audit",
        interactive_confirmed: bool = False,
    ) -> dict[str, Any]:
        self.require_setup()
        proposal_path = self._rule_proposal_path(rule_id)
        if not self.fs.exists(proposal_path):
            raise AnchorError(f"Rule proposal '{rule_id}' does not exist.")
        rule = self._read_json(proposal_path)
        self._validate_rule_document(rule, expected_id=rule_id, expected_status="proposed")
        rule["status"] = "approved"
        rule["approval"] = self._approval_record(
            by,
            provenance,
            interactive_confirmed=interactive_confirmed,
        )
        rule["approved_at"] = rule["approval"]["at"]
        rule["approved_document_digest"] = self._approved_rule_document_digest(rule)
        approved_path = self.anchor_dir / "rules" / "approved" / proposal_path.name
        active = self._active_rules_with(rule)
        self._write_json(approved_path, rule)
        self._write_json(self.anchor_dir / "rules" / "active.json", active)
        config = self._read_json(self.config_path)
        self._refresh_config_ruleset_metadata(config)
        self._write_json(self.config_path, config)
        self.fs.unlink(proposal_path)
        self._append_event({"type": "rule.approved", "rule_id": rule_id, "at": self._timestamp()})
        return rule

    def supersede_rule(
        self,
        *,
        old_rule_id: str,
        new_rule_id: str,
        by: str,
        reason: str,
        provenance: str = "audit",
        interactive_confirmed: bool = False,
    ) -> dict[str, Any]:
        self.require_setup()
        self._validate_rule_id(old_rule_id)
        self._validate_rule_id(new_rule_id)
        if old_rule_id == new_rule_id:
            raise AnchorError("A rule cannot supersede itself.")
        old_rule_path = self._rule_approved_path(old_rule_id)
        new_rule_path = self._rule_approved_path(new_rule_id)
        if not self.fs.exists(old_rule_path) or not self.fs.exists(new_rule_path):
            raise AnchorError("Both rules must be approved before one can supersede the other.")
        old_rule = self._read_json(old_rule_path)
        new_rule = self._read_json(new_rule_path)
        self._validate_rule_document(
            old_rule,
            expected_id=old_rule_id,
            expected_status="approved",
            require_approval_digest=False,
        )
        self._validate_rule_document(new_rule, expected_id=new_rule_id, expected_status="approved")
        if new_rule.get("superseded_by"):
            raise AnchorError("A superseded rule cannot become active again through implicit supersession.")
        if old_rule["category"] != new_rule["category"]:
            raise AnchorError("Only rules in the same category can supersede each other.")

        active_path = self.anchor_dir / "rules" / "active.json"
        active = self._read_json(active_path) if self.fs.exists(active_path) else {"version": 1, "rules": {}}
        category = old_rule["category"]
        if active["rules"].get(category) != old_rule_id:
            raise AnchorError(f"Rule '{old_rule_id}' is not the active {category} rule.")
        approval = self._approval_record(
            by,
            provenance,
            interactive_confirmed=interactive_confirmed,
        )
        supersession = {
            "from": old_rule_id,
            "to": new_rule_id,
            "reason": self._required_text(reason, "Supersession reason"),
            **approval,
        }
        active["rules"][category] = new_rule_id
        active.setdefault("history", []).append(supersession)
        old_rule["superseded_by"] = {"rule_id": new_rule_id, **approval, "reason": supersession["reason"]}
        self._write_json(old_rule_path, old_rule)
        self._write_json(active_path, active)
        config = self._read_json(self.config_path)
        self._refresh_config_ruleset_metadata(config)
        self._write_json(self.config_path, config)
        self._append_event({"type": "rule.superseded", **supersession})
        return {"active_rule": new_rule_id, "category": category, "supersession": supersession}

    def list_rules(self) -> list[dict[str, Any]]:
        self.require_setup()
        rules = []
        for path in sorted(self.fs.glob(self.anchor_dir / "rules" / "proposals", "*.json")):
            rule = self._read_json(path)
            rule["location"] = "proposal"
            rules.append(rule)
        for path in sorted(self.fs.glob(self.anchor_dir / "rules" / "approved", "*.json")):
            rule = self._read_json(path)
            rule["location"] = "approved"
            rules.append(rule)
        return rules

    def detect_agent_capabilities(self) -> dict[str, Any]:
        self.require_setup()
        indicators = {
            "codex": [".codex", "AGENTS.md"],
            "claude-code": ["CLAUDE.md", ".claude"],
            "cursor": [".cursor"],
            "gemini-cli": ["GEMINI.md", ".gemini"],
        }
        detected = [
            name
            for name, markers in indicators.items()
            if any((self.root / marker).exists() for marker in markers)
        ]
        result = {
            "portable_protocol": True,
            "terminal": True,
            "detected_hosts": detected,
            "native_adapter": None,
            "note": "The portable CLI is available even when no native host integration is detected.",
        }
        return result

    def agent_status(self) -> dict[str, Any]:
        result = self.detect_agent_capabilities()
        adapters = sorted(self.fs.glob(self.anchor_dir / "agents" / "adapters", "*.json"))
        result["active_adapters"] = [path.stem for path in adapters]
        return result

    def preview_agent_setup(self, host: str) -> list[str]:
        if host != "portable":
            raise AnchorError("Only the agent-neutral 'portable' adapter is available in this first release.")
        return [
            "Anchor agent setup preview for portable",
            "Will create: .anchor/agents/adapters/portable.json with command and protocol metadata.",
            "Will not: install a host plugin, modify host configuration, or change application source.",
            f"From {self.root}, apply with: anchor agent setup portable --apply",
        ]

    def setup_agent(self, host: str) -> dict[str, Any]:
        self.require_setup()
        self.preview_agent_setup(host)
        adapter = {
            "host": host,
            "source_of_truth": "anchor CLI and .anchor state",
            "commands": [
                "help",
                "status",
                "start",
                "brief",
                "plan",
                "approve",
                "implement",
                "review",
                "precommit",
                "verify",
                "revise",
                "close",
            ],
            "installed_at": self._timestamp(),
        }
        self._write_json(self.anchor_dir / "agents" / "adapters" / f"{host}.json", adapter)
        self._append_event({"type": "agent.adapter.setup", "host": host, "at": self._timestamp()})
        return adapter

    def _active_rules_with(self, rule: dict[str, Any]) -> dict[str, Any]:
        path = self.anchor_dir / "rules" / "active.json"
        active = self._read_json(path) if self.fs.exists(path) else {"version": 1, "rules": {}}
        existing = active["rules"].get(rule["category"])
        if not existing:
            active["rules"][rule["category"]] = rule["id"]
        return active

    def _active_rules_snapshot(self) -> dict[str, Any]:
        path = self.anchor_dir / "rules" / "active.json"
        active = self._read_json(path) if self.fs.exists(path) else {"version": 1, "rules": {}}
        rules = dict(active["rules"])
        documents = {}
        for category, rule_id in sorted(rules.items()):
            approved_path = self._rule_approved_path(rule_id)
            if not self.fs.exists(approved_path):
                raise AnchorError(f"Active rule '{rule_id}' is missing its approved document.")
            rule = self._read_json(approved_path)
            self._validate_rule_document(rule, expected_id=rule_id, expected_status="approved")
            if rule.get("superseded_by"):
                raise AnchorError(f"Active rule '{rule_id}' is marked as superseded.")
            documents[category] = {
                "id": rule["id"],
                "version": rule["version"],
                "wording": rule["wording"],
                "scope": rule["scope"],
                "rationale": rule["rationale"],
                "approved_by": rule.get("approval", {}).get("by"),
                "approved_at": rule.get("approved_at"),
                "document_digest": rule["approved_document_digest"],
            }
        snapshot = {"rules": rules, "documents": documents}
        return {"version": self._ruleset_version(snapshot), **snapshot}

    def _refresh_config_ruleset_metadata(self, config: dict[str, Any]) -> None:
        try:
            config["ruleset_version"] = self._active_rules_snapshot()["version"]
        except AnchorError:
            # A replacement document may be needed to migrate another active legacy
            # rule. Keep this completed rule operation auditable and let `doctor`
            # report that the active ruleset still needs migration.
            config["ruleset_integrity"] = "migration-required"
        else:
            config.pop("ruleset_integrity", None)

    @staticmethod
    def _ruleset_version(rules: dict[str, Any]) -> str:
        encoded = json.dumps(rules, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"ruleset-{hashlib.sha256(encoded).hexdigest()[:12]}"

    def _next_action_for_existing_project(self) -> str:
        if self.fs.exists(self.active_task_path):
            task = self._read_json(self.active_task_path)
            return f"Existing task: {task['title']} ({task['state']}).\n{NEXT_ACTIONS[task['state']]}\n"
        return "Anchor is already configured. Start a task with: anchor start \"short task title\"\n"

    def _task_in_state(self, state: str, action: str) -> dict[str, Any]:
        return self._task_in_states({state}, action)

    def _task_in_states(self, states: set[str], action: str) -> dict[str, Any]:
        self.require_setup()
        if not self.fs.exists(self.active_task_path):
            raise AnchorError("No active task. Run: anchor start \"short task title\"")
        task = self._read_json(self.active_task_path)
        if task["state"] not in states:
            raise AnchorError(f"Cannot run '{action}' while task is '{task['state']}'.")
        return task

    def _advance_task(self, task: dict[str, Any], action: str, state: str) -> dict[str, Any]:
        task["state"] = state
        self._append_task_event(task, f"task.{action}")
        self._write_json(self.active_task_path, task)
        self._write_next_action(f"{NEXT_ACTIONS[state]}\n")
        return task

    def _detect_stack(self) -> list[str]:
        markers = {
            "python": ("pyproject.toml", "requirements.txt", "Pipfile"),
            "node": ("package.json",),
            "rust": ("Cargo.toml",),
            "go": ("go.mod",),
            "dotnet": ("*.sln", "*.csproj"),
        }
        found = []
        for stack, patterns in markers.items():
            if any(self.root.glob(pattern) for pattern in patterns):
                found.append(stack)
        return found

    def _rule_document(self, rule_id: str, category: str, wording: str, *, source: str) -> dict[str, Any]:
        return {
            "id": rule_id,
            "version": 1,
            "category": category,
            "status": "proposed",
            "wording": wording,
            "scope": "project",
            "rationale": "Rules require explicit engineer approval before enforcement.",
            "source": source,
            "created_at": self._timestamp(),
        }

    def _rule_proposal_path(self, rule_id: str) -> Path:
        return self._rule_path("proposals", rule_id)

    def _rule_approved_path(self, rule_id: str) -> Path:
        return self._rule_path("approved", rule_id)

    def _rule_path(self, location: str, rule_id: str) -> Path:
        self._validate_rule_id(rule_id)
        base = self.fs.path(".anchor", "rules", location)
        candidate = self.fs.path(".anchor", "rules", location, f"{rule_id}.json")
        if candidate.parent != base:
            raise AnchorError("Rule path escapes the expected rules directory.")
        return candidate

    @staticmethod
    def _validate_rule_id(rule_id: str) -> None:
        if not RULE_ID_PATTERN.fullmatch(rule_id):
            raise AnchorError(
                "Invalid rule ID. Use lowercase letters, digits, and hyphens only (1-128 characters)."
            )

    def _validate_rule_document(
        self,
        rule: dict[str, Any],
        *,
        expected_id: str,
        expected_status: str,
        require_approval_digest: bool = True,
    ) -> None:
        if rule.get("id") != expected_id:
            raise AnchorError("Rule document ID does not match its filename.")
        if rule.get("status") != expected_status:
            raise AnchorError(f"Rule '{expected_id}' must be {expected_status!r} before this action.")
        if rule.get("category") not in RULE_CATEGORIES:
            raise AnchorError(f"Rule '{expected_id}' has an invalid category.")
        for field in ("wording", "scope", "rationale"):
            value = rule.get(field)
            if not isinstance(value, str) or not value.strip():
                raise AnchorError(f"Rule '{expected_id}' has an invalid {field}.")
        if expected_status == "approved":
            approved_digest = rule.get("approved_document_digest")
            if not isinstance(approved_digest, str):
                if not require_approval_digest:
                    return
                raise AnchorError(
                    f"Approved rule '{expected_id}' uses the legacy format without an approval-time document digest. "
                    "To migrate it, propose and approve a new version, then explicitly supersede this rule."
                )
            if approved_digest != self._approved_rule_document_digest(rule):
                raise AnchorError(
                    f"Approved rule '{expected_id}' changed after approval. "
                    "Propose and approve a new version instead."
                )

    def _append_task_event(self, task: dict[str, Any], event_type: str) -> None:
        event = {"type": event_type, "at": self._timestamp(), "state": task["state"]}
        task["events"].append(event)
        self._append_event({"task_id": task["id"], **event})

    def _append_event(self, event: dict[str, Any]) -> None:
        path = self.anchor_dir / "events.jsonl"
        self.fs.append_text(path, json.dumps(event, sort_keys=True) + "\n")

    def _ensure_graphify_ignore(self) -> None:
        path = self.root / ".graphifyignore"
        required_lines = [
            ".anchor/",
            "graphify-out/",
            ".env",
            ".env.*",
            ".venv/",
            "venv/",
            "node_modules/",
            "dist/",
            "build/",
        ]
        current = self.fs.read_text(path).splitlines() if self.fs.exists(path) else []
        additions = [line for line in required_lines if line not in current]
        if additions:
            prefix = "\n" if current else ""
            self._write_text(path, "\n".join(current) + prefix + "\n".join(additions) + "\n")

    def _write_next_action(self, content: str) -> None:
        self._write_text(self.next_action_path, content)

    def next_action(self) -> str:
        return self.fs.read_text(self.next_action_path).strip()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(self.fs.read_text(path))
        except (AnchorError, UnicodeDecodeError) as error:
            raise AnchorError(f"Cannot read Anchor state at {path}.") from error
        except json.JSONDecodeError as error:
            raise AnchorError(f"Anchor state is invalid JSON at {path}. Run: anchor doctor") from error
        if not isinstance(data, dict):
            raise AnchorError(f"Anchor state at {path} must be a JSON object. Run: anchor doctor")
        return data

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        self._write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")

    def _write_json_if_missing(self, path: Path, data: dict[str, Any]) -> None:
        if not self.fs.exists(path):
            self._write_json(path, data)

    def _write_text(self, path: Path, content: str) -> None:
        self.fs.atomic_write_text(path, content)

    def _write_text_if_missing(self, path: Path, content: str) -> None:
        if not self.fs.exists(path):
            self._write_text(path, content)

    @staticmethod
    def _required_text(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise AnchorError(f"{label} cannot be empty.")
        return normalized

    @staticmethod
    def _document_digest(document: Any) -> str:
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _task_approval_subject(task: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": task.get("id"),
            "title": task.get("title"),
            "brief": task.get("brief"),
            "brief_record": task.get("brief_record"),
            "plan": task.get("plan"),
            "ruleset": task.get("ruleset"),
        }

    def _task_approval_digests(self, subject: dict[str, Any]) -> dict[str, str]:
        return {
            "brief_digest": self._document_digest(subject["brief"]),
            "brief_record_digest": self._document_digest(subject["brief_record"]),
            "plan_digest": self._document_digest(subject["plan"]),
            "ruleset_digest": self._document_digest(subject["ruleset"]),
            "task_digest": self._document_digest(subject),
        }

    def _ensure_approval_matches_task(self, task: dict[str, Any]) -> None:
        approval = task.get("approval")
        subject = self._task_approval_subject(task)
        expected = self._task_approval_digests(subject)
        changed = [
            label.removesuffix("_digest")
            for label, digest in expected.items()
            if label != "task_digest"
            if not isinstance(approval, dict) or approval.get(label) != digest
        ]
        if (
            not isinstance(approval, dict)
            or approval.get("task_digest") != expected["task_digest"]
        ) and not changed:
            changed.append("task")
        if not changed:
            return

        if "brief" in changed or "brief_record" in changed:
            state = "briefing"
            next_action = "The approved brief changed. Record the brief again, then create and approve a plan."
        else:
            state = "planned"
            next_action = "The approved plan or ruleset changed. Review it, then run: anchor approve --by <engineer>"
        invalidation = {
            "at": self._timestamp(),
            "previous_state": task["state"],
            "changed_artifacts": changed,
            "approval": approval,
            "ruleset": task.get("ruleset"),
        }
        task.setdefault("approval_invalidations", []).append(invalidation)
        for field in ("approval", "ruleset", "quality", "verification"):
            task.pop(field, None)
        if state == "briefing":
            invalidation["plan"] = task.pop("plan", None)
            invalidation["brief_record"] = task.pop("brief_record", None)
        task["state"] = state
        self._append_task_event(task, "task.approval.invalidated")
        self._write_json(self.active_task_path, task)
        self._write_next_action(f"{next_action}\n")
        raise AnchorError(next_action)

    @staticmethod
    def _approved_rule_document_digest(rule: dict[str, Any]) -> str:
        canonical = {
            key: value
            for key, value in rule.items()
            if key not in {"approved_document_digest", "superseded_by"}
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def _approval_record(
        self,
        by: str,
        provenance: str,
        *,
        interactive_confirmed: bool = False,
    ) -> dict[str, str]:
        if provenance not in APPROVAL_PROVENANCE:
            options = ", ".join(sorted(APPROVAL_PROVENANCE))
            raise AnchorError(f"Approval provenance must be one of: {options}.")
        if provenance == "interactive-tty" and not interactive_confirmed:
            raise AnchorError(
                "interactive-tty provenance requires an explicit terminal confirmation."
            )
        record = {
            "by": self._required_text(by, "Engineer name"),
            "provenance": provenance,
            "at": self._timestamp(),
        }
        if provenance == "interactive-tty":
            record["confirmation"] = "typed"
        return record

    def _ensure_quality_matches_workspace(self, task: dict[str, Any]) -> None:
        quality_runs = task.get("quality", [])
        if not quality_runs or quality_runs[-1].get("status") != "passed":
            raise AnchorError("A passing pre-commit result is required before verification or close.")
        recorded = quality_runs[-1].get("workspace_fingerprint")
        if not isinstance(recorded, dict):
            self._invalidate_quality(
                task,
                recorded_fingerprint=None,
                current_fingerprint=None,
                reason="The recorded quality evidence predates workspace fingerprints.",
            )
            raise AnchorError(
                "The latest quality result has no workspace fingerprint. "
                "The task returned to review_ready; rerun: anchor precommit"
            )
        current = workspace_fingerprint(self.root)
        if current.get("digest") == recorded.get("digest"):
            return
        self._invalidate_quality(
            task,
            recorded_fingerprint=recorded,
            current_fingerprint=current,
            reason="Code changed after the quality gate.",
        )
        raise AnchorError("Code changed after the quality gate. The task returned to review_ready.")

    def _invalidate_quality(
        self,
        task: dict[str, Any],
        *,
        recorded_fingerprint: dict[str, Any] | None,
        current_fingerprint: dict[str, Any] | None,
        reason: str,
    ) -> None:
        previous_verification = task.pop("verification", None)
        if previous_verification is not None:
            task.setdefault("verification_invalidations", []).append(
                {
                    "at": self._timestamp(),
                    "verification": previous_verification,
                    "reason": reason,
                }
            )
        task["state"] = "review_ready"
        task.setdefault("quality_invalidations", []).append(
            {
                "at": self._timestamp(),
                "reason": reason,
                "recorded_fingerprint": recorded_fingerprint,
                "current_fingerprint": current_fingerprint,
            }
        )
        self._append_task_event(task, "task.quality.invalidated")
        self._write_json(self.active_task_path, task)
        self._write_next_action(
            "Quality evidence was invalidated. Review the current diff and rerun: anchor precommit\n"
        )
