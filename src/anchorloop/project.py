from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .quality import run_precommit


class AnchorError(Exception):
    """Raised when an Anchor command would break an explicit workflow rule."""


TASK_TRANSITIONS = {
    "implement": {"approved": "implementing"},
    "review": {"implementing": "review_ready"},
    "precommit": {"review_ready": "quality_checked"},
    "close": {"verified": "closed"},
}

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
            "Will create: .anchor/ state, portable protocol, baseline rule proposals, and Graphify integration metadata.",
            "Will not: edit application source, install packages, install Graphify, or create a Git commit.",
            "Baseline rules remain inactive until an engineer approves their exact versions.",
            f"Detected project markers: {', '.join(self.detected_stack) or 'none'}.",
            f"Apply with: anchor {self.mode} --path {self.root} --apply",
        ]


class AnchorProject:
    """A deep local module for Anchor state, rules, and task transitions."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
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
        created = not self.config_path.exists()

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
            (self.anchor_dir / directory).mkdir(parents=True, exist_ok=True)

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
        self._write_json_if_missing(
            self.anchor_dir / "protocol" / "anchor-protocol.json",
            {
                "version": 1,
                "source_of_truth": "anchor CLI and .anchor state",
                "commands": ["brief", "plan", "approve", *sorted(TASK_TRANSITIONS), "verify"],
                "states": list(NEXT_ACTIONS),
                "host_adapters": ["portable-instructions", "terminal", "skills", "slash-commands", "hooks", "mcp"],
            },
        )
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
            if not proposal_path.exists() and not approved_path.exists():
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
        if not self.config_path.exists():
            raise AnchorError("Anchor is not configured here. Run: anchor add --apply")

    def status(self) -> dict[str, Any]:
        self.require_setup()
        config = self._read_json(self.config_path)
        task = self._read_json(self.active_task_path) if self.active_task_path.exists() else None
        return {
            "project": config["name"],
            "root": str(self.root),
            "ruleset_version": config.get("ruleset_version"),
            "active_task": None if task is None else {"id": task["id"], "title": task["title"], "state": task["state"]},
            "next_action": self.next_action_path.read_text(encoding="utf-8").strip(),
        }

    def start_task(self, title: str) -> dict[str, Any]:
        self.require_setup()
        if self.active_task_path.exists():
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
        task["brief_record"] = {"by": engineer, "at": self._timestamp()}
        self._append_task_event(task, "task.brief.recorded")
        self._write_json(self.active_task_path, task)
        self._write_next_action("Brief recorded. Prepare a concrete plan, then run: anchor plan --summary <text>\n")
        return task

    def plan_task(self, summary: str) -> dict[str, Any]:
        task = self._task_in_state("briefing", "plan")
        if any(not value for value in task["brief"].values()) or "brief_record" not in task:
            raise AnchorError("Record the complete engineer brief before planning.")
        task["plan"] = {"summary": self._required_text(summary, "Plan summary"), "at": self._timestamp()}
        return self._advance_task(task, "plan", "planned")

    def approve_task(self, by: str) -> dict[str, Any]:
        task = self._task_in_state("planned", "approve")
        if "plan" not in task:
            raise AnchorError("A recorded plan is required before approval.")
        snapshot = self._active_rules_snapshot()
        task["ruleset"] = snapshot
        task["approval"] = {
            "by": self._required_text(by, "Engineer name"),
            "at": self._timestamp(),
            "plan_summary": task["plan"]["summary"],
            "ruleset_version": snapshot["version"],
        }
        return self._advance_task(task, "approve", "approved")

    def verify_task(self, *, by: str, result: str, reason: str) -> dict[str, Any]:
        task = self._task_in_state("quality_checked", "verify")
        verification = {
            "by": self._required_text(by, "Engineer name"),
            "result": result,
            "reason": self._required_text(reason, "Verification reason"),
            "at": self._timestamp(),
        }
        task["verification"] = verification
        if result == "fail":
            self._append_task_event(task, "task.verify.failed")
            self._write_json(self.active_task_path, task)
            self._write_next_action("Verification failed. Record a follow-up or return to implementation with a new approved task.\n")
            raise AnchorError("Engineer verification failed; the task cannot be closed.")
        return self._advance_task(task, "verify", "verified")

    def transition(self, action: str) -> dict[str, Any]:
        self.require_setup()
        if not self.active_task_path.exists():
            raise AnchorError("No active task. Run: anchor start \"short task title\"")
        task = self._read_json(self.active_task_path)
        if action == "close":
            verification = task.get("verification", {})
            if verification.get("result") not in {"pass", "partial", "not-applicable"}:
                raise AnchorError("A recorded engineer verification is required before close.")
        state = task["state"]
        expected = TASK_TRANSITIONS.get(action, {})
        if state not in expected:
            allowed = ", ".join(name for name, states in TASK_TRANSITIONS.items() if state in states)
            detail = f" Allowed next command: anchor {allowed}." if allowed else ""
            raise AnchorError(f"Cannot run '{action}' while task is '{state}'.{detail}")
        task["state"] = expected[state]
        self._append_task_event(task, f"task.{action}")
        if action == "close":
            closed_path = self.anchor_dir / "tasks" / "closed" / f"{task['id']}.json"
            self._write_json(closed_path, task)
            self.active_task_path.unlink()
            self._write_next_action("No active task. Start the next one with: anchor start \"short task title\"\n")
            return task
        self._write_json(self.active_task_path, task)
        self._write_next_action(f"{NEXT_ACTIONS[task['state']]}\n")
        return task

    def precommit(self) -> dict[str, Any]:
        self.require_setup()
        if not self.active_task_path.exists():
            raise AnchorError("No active task. Run: anchor start \"short task title\"")
        task = self._read_json(self.active_task_path)
        if task["state"] != "review_ready":
            raise AnchorError(f"Cannot run 'precommit' while task is '{task['state']}'.")
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
        if category not in {"code-quality", "security", "structure"}:
            raise AnchorError("Rule category must be one of: code-quality, security, structure.")
        normalized_wording = wording.strip()
        if not normalized_wording:
            raise AnchorError("Rule wording cannot be empty.")
        rule_id = f"rule-{self._slug(category)}-{uuid4().hex[:8]}"
        document = self._rule_document(rule_id, category, normalized_wording, source="Engineer or agent proposal")
        self._write_json(self._rule_proposal_path(rule_id), document)
        self._append_event({"type": "rule.proposed", "rule_id": rule_id, "at": self._timestamp()})
        return document

    def approve_rule(self, rule_id: str) -> dict[str, Any]:
        self.require_setup()
        proposal_path = self._rule_proposal_path(rule_id)
        if not proposal_path.exists():
            raise AnchorError(f"Rule proposal '{rule_id}' does not exist.")
        rule = self._read_json(proposal_path)
        rule["status"] = "approved"
        rule["approved_at"] = self._timestamp()
        approved_path = self.anchor_dir / "rules" / "approved" / proposal_path.name
        self._write_json(approved_path, rule)
        proposal_path.unlink()
        active = self._active_rules_with(rule)
        self._write_json(self.anchor_dir / "rules" / "active.json", active)
        config = self._read_json(self.config_path)
        config["ruleset_version"] = self._ruleset_version(active["rules"])
        self._write_json(self.config_path, config)
        self._append_event({"type": "rule.approved", "rule_id": rule_id, "at": self._timestamp()})
        return rule

    def list_rules(self) -> list[dict[str, Any]]:
        self.require_setup()
        rules = []
        for path in sorted((self.anchor_dir / "rules" / "proposals").glob("*.json")):
            rule = self._read_json(path)
            rule["location"] = "proposal"
            rules.append(rule)
        for path in sorted((self.anchor_dir / "rules" / "approved").glob("*.json")):
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
        adapters = sorted((self.anchor_dir / "agents" / "adapters").glob("*.json"))
        result["active_adapters"] = [path.stem for path in adapters]
        return result

    def preview_agent_setup(self, host: str) -> list[str]:
        if host != "portable":
            raise AnchorError("Only the agent-neutral 'portable' adapter is available in this first release.")
        return [
            "Anchor agent setup preview for portable",
            "Will create: .anchor/agents/adapters/portable.json with command and protocol metadata.",
            "Will not: install a host plugin, modify host configuration, or change application source.",
            "Apply with: anchor agent setup portable --apply",
        ]

    def setup_agent(self, host: str) -> dict[str, Any]:
        self.require_setup()
        self.preview_agent_setup(host)
        adapter = {
            "host": host,
            "source_of_truth": "anchor CLI and .anchor state",
            "commands": ["help", "status", "start", "brief", "plan", "approve", "implement", "review", "precommit", "verify", "close"],
            "installed_at": self._timestamp(),
        }
        self._write_json(self.anchor_dir / "agents" / "adapters" / f"{host}.json", adapter)
        self._append_event({"type": "agent.adapter.setup", "host": host, "at": self._timestamp()})
        return adapter

    def _active_rules_with(self, rule: dict[str, Any]) -> dict[str, Any]:
        path = self.anchor_dir / "rules" / "active.json"
        active = self._read_json(path) if path.exists() else {"version": 1, "rules": {}}
        active["rules"][rule["category"]] = rule["id"]
        return active

    def _active_rules_snapshot(self) -> dict[str, Any]:
        path = self.anchor_dir / "rules" / "active.json"
        active = self._read_json(path) if path.exists() else {"version": 1, "rules": {}}
        rules = dict(active["rules"])
        return {"version": self._ruleset_version(rules), "rules": rules}

    @staticmethod
    def _ruleset_version(rules: dict[str, str]) -> str:
        encoded = json.dumps(rules, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"ruleset-{hashlib.sha256(encoded).hexdigest()[:12]}"

    def _next_action_for_existing_project(self) -> str:
        if self.active_task_path.exists():
            task = self._read_json(self.active_task_path)
            return f"Existing task: {task['title']} ({task['state']}).\n{NEXT_ACTIONS[task['state']]}\n"
        return "Anchor is already configured. Start a task with: anchor start \"short task title\"\n"

    def _task_in_state(self, state: str, action: str) -> dict[str, Any]:
        self.require_setup()
        if not self.active_task_path.exists():
            raise AnchorError("No active task. Run: anchor start \"short task title\"")
        task = self._read_json(self.active_task_path)
        if task["state"] != state:
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
        return self.anchor_dir / "rules" / "proposals" / f"{rule_id}.json"

    def _append_task_event(self, task: dict[str, Any], event_type: str) -> None:
        event = {"type": event_type, "at": self._timestamp(), "state": task["state"]}
        task["events"].append(event)
        self._append_event({"task_id": task["id"], **event})

    def _append_event(self, event: dict[str, Any]) -> None:
        path = self.anchor_dir / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

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
        current = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        additions = [line for line in required_lines if line not in current]
        if additions:
            prefix = "\n" if current else ""
            self._write_text(path, "\n".join(current) + prefix + "\n".join(additions) + "\n")

    def _write_next_action(self, content: str) -> None:
        self._write_text(self.next_action_path, content)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        AnchorProject._write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _write_json_if_missing(path: Path, data: dict[str, Any]) -> None:
        if not path.exists():
            AnchorProject._write_json(path, data)

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _write_text_if_missing(path: Path, content: str) -> None:
        if not path.exists():
            AnchorProject._write_text(path, content)

    @staticmethod
    def _required_text(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise AnchorError(f"{label} cannot be empty.")
        return normalized
