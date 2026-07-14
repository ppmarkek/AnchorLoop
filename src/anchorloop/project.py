from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar
from uuid import uuid4

from .command import display_command
from .quality import run_precommit, workspace_fingerprint
from .project_lock import ProjectLock
from .safe_fs import AnchorError, SafeProjectFS
from .transaction import ProjectTransaction, TransactionManager


TASK_TRANSITIONS = {
    "implement": {"approved": "implementing"},
    "review": {"implementing": "review_ready"},
    "precommit": {"review_ready": "quality_checked"},
    "close": {"verified": "closed"},
}

RULE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
APPROVAL_PROVENANCE = {"audit", "interactive-tty"}
RULE_CATEGORIES = {"code-quality", "security", "structure"}
TASK_MODES = {"FAST", "STANDARD", "CAREFUL"}
TASK_ID_PATTERN = re.compile(r"^al-[0-9]{8}-[a-f0-9]{6}$")
_START_TASK_ARGUMENTS = 'start "short task title"'
BRIEF_FIELDS = ("outcome", "scope", "constraints", "invariant", "uncertainty")
VERIFICATION_RESULTS = {"pass", "fail", "partial", "not-applicable"}
CAREFUL_RECALL_DELAY_HOURS = 24

# These are deliberately conservative signals.  They promote a task only when
# an engineer explicitly names a sensitive area or provides a recognisably
# sensitive path.  A vague mention of a technology is not enough to change a
# task's ownership mode.
_CAREFUL_TEXT_SIGNALS: dict[str, tuple[str, ...]] = {
    "migration": (
        "migration",
        "migrate",
        "database schema",
        "schema migration",
        "миграц",
        "схема базы",
        "изменение схемы",
    ),
    "authentication or authorization": (
        "authentication",
        "authorization",
        "oauth",
        "openid",
        "jwt",
        "аутентификац",
        "авторизац",
    ),
    "payment": (
        "payment",
        "billing",
        "stripe",
        "checkout payment",
        "платеж",
        "платёж",
        "оплат",
        "биллинг",
    ),
    "secret or cryptography": (
        "secret",
        "credential",
        "private key",
        "cryptograph",
        "encryption",
        "секрет",
        "парол",
        "токен",
        "ключ",
        "криптограф",
        "шифрован",
    ),
    "concurrency": (
        "concurren",
        "race condition",
        "thread safety",
        "параллельн",
        "конкурентн",
        "гонк",
        "потокобезопас",
    ),
    "infrastructure": (
        "infrastructure",
        "production deploy",
        "kubernetes",
        "terraform",
        "инфраструктур",
        "деплой",
        "развертыван",
        "развёртыван",
    ),
    "destructive change": (
        "destructive",
        "irreversible",
        "drop table",
        "purge",
        "delete production",
        "удалени",
        "уничтожени",
        "необратим",
        "очистк",
    ),
    "public API": (
        "public api",
        "external api",
        "openapi",
        "публичн api",
        "внешн api",
        "публичного api",
    ),
    "new dependency": (
        "new dependency",
        "add dependency",
        "add package",
        "новая зависим",
        "добавить зависим",
        "новый пакет",
    ),
}

_CAREFUL_PATH_SIGNALS: dict[str, tuple[str, ...]] = {
    "migration path": (
        "/migrations/",
        "/migration/",
        "/alembic/",
        "schema.prisma",
        "/prisma/schema",
    ),
    "authentication or authorization path": (
        "/auth/",
        "/authentication/",
        "/authorization/",
        "/oauth/",
        "/identity/",
        "/login/",
    ),
    "payment path": ("/payment/", "/payments/", "/billing/", "/checkout/", "/stripe/"),
    "public API path": ("/api/", "/openapi/", "/routes/", "/controllers/"),
    "concurrency path": ("/locks/", "/mutex/", "/semaphore/", "/concurrency/"),
    "infrastructure path": ("/infra/", "/terraform/", "/kubernetes/", "/.github/workflows/"),
    "dependency manifest": (
        "/package-lock.json",
        "/pnpm-lock.yaml",
        "/yarn.lock",
        "/poetry.lock",
        "/requirements.txt",
        "/cargo.lock",
        "/go.mod",
        "/package.json",
        "/pyproject.toml",
    ),
}

_ReturnT = TypeVar("_ReturnT")


class StateRecordedError(AnchorError):
    """A command failed after intentionally recording a durable workflow result."""


def mutating(
    command: str,
    *,
    allow_unconfigured: bool = False,
) -> Callable[[Callable[..., _ReturnT]], Callable[..., _ReturnT]]:
    """Run one public mutation under the project lock and redo journal."""

    def decorate(function: Callable[..., _ReturnT]) -> Callable[..., _ReturnT]:
        @wraps(function)
        def wrapped(self: "AnchorProject", *args: Any, **kwargs: Any) -> _ReturnT:
            with self._mutation(command, allow_unconfigured=allow_unconfigured):
                return function(self, *args, **kwargs)

        return wrapped

    return decorate


def consistent_read(command: str) -> Callable[[Callable[..., _ReturnT]], Callable[..., _ReturnT]]:
    """Serialize a state read with replay of any prepared transaction."""

    def decorate(function: Callable[..., _ReturnT]) -> Callable[..., _ReturnT]:
        @wraps(function)
        def wrapped(self: "AnchorProject", *args: Any, **kwargs: Any) -> _ReturnT:
            with self._consistent_read(command):
                return function(self, *args, **kwargs)

        return wrapped

    return decorate


NEXT_ACTIONS = {
    "briefing": "Complete the engineer brief, then run: {command} plan",
    "planned": "Inspect the plan and required human artifact, then run: {command} approve",
    "approved": "Implementation is authorised. Run: {command} implement",
    "implementing": "Make the approved patch and run automated checks, then: {command} review",
    "review_ready": "Review the evidence and run the quality gate: {command} precommit",
    "quality_checked": "Perform the manual verification, then run: {command} verify",
    "verified": "Close the task when the outcome is accepted: {command} close",
}


def _next_action(state: str) -> str:
    return NEXT_ACTIONS[state].format(command=display_command())

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
            "Will create or append managed cache and recovery rules in .gitignore and .anchor/.gitignore without removing existing lines.",
            "Will not: edit application source, install packages, install Graphify, or create a Git commit.",
            "Baseline rules remain inactive until an engineer approves their exact versions.",
            f"Detected project markers: {', '.join(self.detected_stack) or 'none'}.",
            f"From {self.root}, apply with: {display_command(f'{self.mode} --apply')}",
        ]


class AnchorProject:
    """A deep local module for Anchor state, rules, and task transitions."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.fs = SafeProjectFS(self.root)
        self.anchor_dir = self.root / ".anchor"
        self._mutation_depth = 0
        self._transaction: ProjectTransaction | None = None
        self._transaction_manager: TransactionManager | None = None
        self._staged_files: dict[Path, bytes | None] = {}
        self._staged_events: list[dict[str, Any]] = []

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

    @mutating("project.setup", allow_unconfigured=True)
    def apply_setup(self, mode: str) -> bool:
        self.preview_setup(mode)
        self.fs.ensure_directory(self.anchor_dir)
        created = not self._exists(self.config_path)

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
            "version": 3,
            "source_of_truth": "anchor CLI and .anchor state",
            "commands": [
                "brief",
                "plan",
                "approve",
                "revise",
                *sorted(TASK_TRANSITIONS),
                "verify",
                "recall",
                "outcome",
                "report",
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
            current_protocol = self._read_json(protocol_path) if self._exists(protocol_path) else {}
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
        self._ensure_project_gitignore()
        self._ensure_anchor_gitignore()
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
            if not self._exists(proposal_path) and not self._exists(approved_path):
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
        if not self._exists(self.config_path):
            raise AnchorError(
                f"Anchor is not configured here. Run: {display_command('add --apply')}"
            )

    @consistent_read("status")
    def status(self) -> dict[str, Any]:
        self.require_setup()
        config = self._read_json(self.config_path)
        task = self._read_json(self.active_task_path) if self._exists(self.active_task_path) else None
        if task is not None:
            self.validate_task_schema(task)
        return {
            "project": config["name"],
            "root": str(self.root),
            "ruleset_version": config.get("ruleset_version"),
            "active_task": None if task is None else {"id": task["id"], "title": task["title"], "state": task["state"]},
            "next_action": self.next_action(),
            "pending_recalls": self._pending_recalls(),
        }

    def _pending_recalls(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        recalls: list[dict[str, Any]] = []
        closed_directory = self.anchor_dir / "tasks" / "closed"
        for path in sorted(self.fs.glob(closed_directory, "*.json")):
            try:
                task = self._read_json(path)
                self.validate_task_schema(task)
                comprehension = task.get("comprehension")
                if not isinstance(comprehension, dict):
                    continue
                due_value = comprehension.get("recall_due_at")
                if not due_value or comprehension.get("delayed_recall") is not None:
                    continue
                task_id = str(task.get("id", path.stem))
                due_at = self._scheduled_recall_due_at(task)
                recalls.append(
                    {
                        "task_id": task_id,
                        "title": task.get("title"),
                        "due_at": due_at.isoformat(),
                        "status": "due" if now >= due_at else "scheduled",
                        "command": display_command(
                            f"recall --task {task_id} --by <engineer> --response <text> --score 0..5"
                        ),
                    }
                )
            except (AnchorError, TypeError, ValueError) as error:
                recalls.append(
                    {
                        "task_id": path.stem,
                        "status": "invalid",
                        "detail": str(error),
                    }
                )
        return sorted(
            recalls,
            key=lambda item: (str(item.get("due_at", "")), str(item["task_id"])),
        )

    def doctor(self, *, strict: bool = False, repair: bool = False) -> dict[str, Any]:
        """Diagnose managed state without crashing on corrupt paths or JSON."""

        checks: list[dict[str, Any]] = []

        def failed(name: str, error: object) -> None:
            checks.append({"name": name, "status": "failed", "detail": str(error)})

        def safe_exists(path: Path, name: str) -> bool | None:
            try:
                return self._exists(path)
            except Exception as error:  # doctor must stay diagnostic on corrupt local state
                failed(name, error)
                return None

        configured = safe_exists(self.config_path, "filesystem-boundary")
        if configured is False:
            anchor_exists = safe_exists(self.anchor_dir, "anchor-directory")
            if anchor_exists:
                try:
                    manager = TransactionManager(self.root)
                    health = manager.inspect()
                    if repair and (health.pending_transactions or health.outbox_events):
                        with ProjectLock(self.root, purpose="doctor.repair-initial-setup"):
                            recovery = manager.recover()
                        checks.append(
                            {
                                "name": "transaction-recovery",
                                "status": "passed",
                                "recovered": recovery.recovered_transactions,
                                "delivered_events": recovery.delivered_events,
                            }
                        )
                    elif health.pending_transactions or health.outbox_events:
                        raise AnchorError(
                            "Interrupted initial setup has durable recovery pending. "
                            f"Run: {display_command('doctor --repair')}"
                        )
                    configured = safe_exists(self.config_path, "config-after-recovery")
                except Exception as error:
                    failed("transaction-health", error)
        if configured is not True:
            if configured is False:
                failed(
                    "config",
                    f"Anchor is not configured. Run: {display_command('add --apply')}",
                )
            return {
                "anchor_configured": False,
                "active_task": False,
                "strict": strict,
                "repair": repair,
                "checks": checks,
                "status": "attention",
            }

        active_task = False
        try:
            lock = ProjectLock(self.root, purpose="doctor.repair") if repair else nullcontext()
            with lock:
                manager = TransactionManager(self.root)
                if repair:
                    try:
                        recovery = manager.recover()
                        checks.append(
                            {
                                "name": "transaction-recovery",
                                "status": "passed",
                                "recovered": recovery.recovered_transactions,
                                "delivered_events": recovery.delivered_events,
                            }
                        )
                    except Exception as error:
                        failed("transaction-recovery", error)
                try:
                    health = manager.inspect()
                    if health.pending_transactions or health.outbox_events:
                        raise AnchorError(
                            "Durable recovery is pending "
                            f"({health.pending_transactions} transaction(s), {health.outbox_events} event(s)). "
                            f"Run: {display_command('doctor --repair')}"
                        )
                    checks.append({"name": "transaction-health", "status": "passed"})
                except Exception as error:
                    failed("transaction-health", error)

                try:
                    config = self._read_json(self.config_path)
                    if config.get("schema_version") != 1:
                        raise AnchorError("Unsupported or missing config schema version.")
                    checks.append({"name": "config", "status": "passed"})
                except Exception as error:
                    failed("config", error)

                task_exists = safe_exists(self.active_task_path, "active-task-path")
                active_task = task_exists is True
                if task_exists:
                    try:
                        task = self._read_json(self.active_task_path)
                        self.validate_task_schema(task)
                        checks.append({"name": "active-task", "status": "passed"})
                    except Exception as error:
                        failed("active-task", error)
                elif task_exists is False:
                    checks.append({"name": "active-task", "status": "not-run", "detail": "no active task"})

                try:
                    closed_directory = self.anchor_dir / "tasks" / "closed"
                    closed_paths = (
                        sorted(self.fs.glob(closed_directory, "*.json"))
                        if self._exists(closed_directory)
                        else []
                    )
                    for closed_path in closed_paths:
                        closed_task = self._read_json(closed_path)
                        self.validate_task_schema(closed_task)
                        comprehension = closed_task.get("comprehension")
                        if (
                            isinstance(comprehension, dict)
                            and comprehension.get("recall_due_at")
                            and comprehension.get("delayed_recall") is None
                        ):
                            self._scheduled_recall_due_at(closed_task)
                    checks.append({"name": "closed-task-recalls", "status": "passed"})
                except Exception as error:
                    failed("closed-task-recalls", error)

                active_rules = self.anchor_dir / "rules" / "active.json"
                rules_exist = safe_exists(active_rules, "active-rules-path")
                if rules_exist:
                    try:
                        rules = self._read_json(active_rules).get("rules", {})
                        if not isinstance(rules, dict):
                            raise AnchorError("Active rules must be a JSON object.")
                        missing = [
                            str(rule_id)
                            for rule_id in rules.values()
                            if safe_exists(self._rule_approved_path(str(rule_id)), "approved-rule-path") is False
                        ]
                        if missing:
                            raise AnchorError(f"Missing approved rule documents: {', '.join(missing)}")
                        self._active_rules_snapshot()
                        checks.append({"name": "active-rules", "status": "passed"})
                    except Exception as error:
                        failed("active-rules", error)
                elif rules_exist is False:
                    checks.append({"name": "active-rules", "status": "not-run", "detail": "no active rules"})

                if strict:
                    strict_files = {
                        "protocol": self.anchor_dir / "protocol" / "anchor-protocol.json",
                        "next-action": self.next_action_path,
                        "event-log": self.anchor_dir / "events.jsonl",
                    }
                    for name, path in strict_files.items():
                        exists = safe_exists(path, f"strict-{name}")
                        if exists is False:
                            failed(f"strict-{name}", f"Required managed file is missing: {path}")
                        elif exists:
                            try:
                                if name == "protocol":
                                    protocol = self._read_json(path)
                                    if not isinstance(protocol.get("version"), int):
                                        raise AnchorError("Protocol version is missing or invalid.")
                                elif name == "next-action" and not self._read_text(path).strip():
                                    raise AnchorError("Next action is empty.")
                                elif name == "event-log":
                                    manager._read_event_log(repair_torn_tail=False)
                                checks.append({"name": f"strict-{name}", "status": "passed"})
                            except Exception as error:
                                failed(f"strict-{name}", error)
        except Exception as error:
            failed("project-lock", error)

        return {
            "anchor_configured": True,
            "active_task": active_task,
            "strict": strict,
            "repair": repair,
            "checks": checks,
            "status": "ok" if all(check["status"] != "failed" for check in checks) else "attention",
        }

    @mutating("task.start")
    def start_task(self, title: str) -> dict[str, Any]:
        self.require_setup()
        if self._exists(self.active_task_path):
            task = self._read_json(self.active_task_path)
            raise AnchorError(f"Task {task['id']} is already active in state {task['state']}.")
        normalized_title = self._required_text(title, "Task title")
        task = {
            "id": f"al-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid4().hex[:6]}",
            "title": normalized_title,
            "state": "briefing",
            "created_at": self._timestamp(),
            "brief": {name: None for name in BRIEF_FIELDS},
            "ruleset": None,
            "events": [],
        }
        self._write_json(self.active_task_path, task)
        self._append_task_event(task, "task.started")
        self._write_json(self.active_task_path, task)
        self._write_next_action(
            "Reply with this engineer brief before planning:\n"
            "Outcome:\nScope / non-goals:\nConstraints:\nInvariant or acceptance case:\nMain uncertainty:\n"
            f"Record it with: {display_command('brief')} --by <engineer> --outcome <text> --scope <text> "
            "--constraints <text> --invariant <text> --uncertainty <text>\n"
        )
        return task

    @mutating("task.brief")
    def record_brief(self, *, by: str, values: dict[str, str]) -> dict[str, Any]:
        task = self._task_in_state("briefing", "brief")
        engineer = self._required_text(by, "Engineer name")
        task["brief"] = self.validate_brief_fields(values)
        task["brief_record"] = {
            "by": engineer,
            "at": self._timestamp(),
            "brief_digest": self._document_digest(task["brief"]),
        }
        self._append_task_event(task, "task.brief.recorded")
        self._write_json(self.active_task_path, task)
        self._write_next_action(
            "Brief recorded. Prepare the engineer-owned plan fields, then inspect: "
            f"{display_command('plan --help')}\n"
        )
        return task

    @mutating("task.plan")
    def plan_task(
        self,
        summary: str,
        *,
        mode: str = "AUTO",
        task_type: str = "general",
        approach: str | None = None,
        rejected_alternative: str | None = None,
        primary_risk: str | None = None,
        verification_strategy: str | None = None,
        human_artifact: str | None = None,
        comprehension: str | None = None,
        rollback_mitigation: str | None = None,
        mode_override_reason: str | None = None,
        by: str | None = None,
    ) -> dict[str, Any]:
        task = self._task_in_states({"briefing", "planned"}, "plan")
        brief_record = task.get("brief_record")
        if (
            any(not value for value in task["brief"].values())
            or not isinstance(brief_record, dict)
            or brief_record.get("brief_digest") != self._document_digest(task["brief"])
        ):
            raise AnchorError("Record the complete engineer brief before planning.")
        normalized_summary = self._required_text(summary, "Plan summary")
        normalized_task_type = self._required_text(task_type, "Task type")
        requested_mode = self._required_text(mode, "Task mode").upper()
        if requested_mode not in {*TASK_MODES, "AUTO"}:
            raise AnchorError("Task mode must be one of: AUTO, FAST, STANDARD, CAREFUL.")
        try:
            approved_risk_rules = self._active_rules_snapshot().get("documents", {})
        except AnchorError:
            # Risk recommendation is advisory. A corrupt active ruleset still
            # blocks approval later, but it must not move that integrity error
            # to planning or make an ordinary task impossible to record.
            approved_risk_rules = {}
        recommended_mode, recommendation_reason = self._recommended_mode(
            normalized_task_type,
            task["brief"],
            title=task["title"],
            approved_rules=approved_risk_rules,
        )
        normalized_mode = recommended_mode if requested_mode == "AUTO" else requested_mode
        ownership_values = {
            "approach": approach,
            "rejected_alternative": rejected_alternative,
            "primary_risk": primary_risk,
            "verification_strategy": verification_strategy,
            "human_artifact": human_artifact,
            "comprehension": comprehension,
            "by": by,
        }
        if normalized_mode == "CAREFUL":
            ownership_values["rollback_mitigation"] = rollback_mitigation
        if normalized_mode in {"STANDARD", "CAREFUL"}:
            missing = [name for name, value in ownership_values.items() if not isinstance(value, str) or not value.strip()]
            if missing:
                raise AnchorError(
                    f"{normalized_mode} planning requires engineer-owned fields: {', '.join(missing)}."
                )

        if self._mode_rank(normalized_mode) < self._mode_rank(recommended_mode):
            if not isinstance(mode_override_reason, str) or not mode_override_reason.strip():
                raise AnchorError(
                    f"This task recommends {recommended_mode} mode ({recommendation_reason}). "
                    "A lower mode requires --mode-override-reason."
                )
        owner = self._required_text(by or brief_record["by"], "Engineer name")
        recorded_at = self._timestamp()
        effective_approach = self._required_text(approach or normalized_summary, "Approach")
        effective_alternative = self._required_text(
            rejected_alternative or "No material alternative recorded for this explicitly selected FAST task.",
            "Rejected alternative",
        )
        effective_risk = self._required_text(primary_risk or task["brief"]["uncertainty"], "Primary risk")
        effective_verification = self._required_text(
            verification_strategy or task["brief"]["invariant"],
            "Verification strategy",
        )
        effective_artifact = (
            self._required_text(human_artifact, "Human artifact")
            if human_artifact is not None
            else None
        )
        effective_comprehension = (
            self._required_text(comprehension, "Comprehension checksum")
            if comprehension is not None
            else None
        )
        if "plan" in task:
            task.setdefault("plan_history", []).append(task["plan"])
        task["mode"] = normalized_mode
        task["task_type"] = normalized_task_type
        task["plan"] = {
            "summary": normalized_summary,
            "approach": effective_approach,
            "rejected_alternative": effective_alternative,
            "primary_risk": effective_risk,
            "verification_strategy": effective_verification,
            "rollback_mitigation": (
                self._required_text(rollback_mitigation, "Rollback or mitigation")
                if rollback_mitigation is not None
                else None
            ),
            "mode_recommendation": {
                "mode": recommended_mode,
                "requested": requested_mode,
                "reason": recommendation_reason,
                "override_reason": mode_override_reason.strip() if isinstance(mode_override_reason, str) else None,
            },
            "at": recorded_at,
        }
        task["human_artifact"] = (
            {
                "content": effective_artifact,
                "by": owner,
                "at": recorded_at,
                "source": "plan-input",
            }
            if effective_artifact is not None
            else None
        )
        task["comprehension"] = {
            "baseline": (
                {
                    "statement": effective_comprehension,
                    "by": owner,
                    "at": recorded_at,
                }
                if effective_comprehension is not None
                else None
            ),
            # The approval binds this delay policy.  The concrete due time is
            # derived from the eventual close time, so long-running tasks do
            # not receive an already-overdue recall check.
            "recall_delay_hours": (
                CAREFUL_RECALL_DELAY_HOURS if normalized_mode == "CAREFUL" else None
            ),
            "recall_due_at": None,
        }
        metrics = task.setdefault("metrics", {})
        metrics["plan_recorded_at"] = recorded_at
        metrics["mode"] = normalized_mode
        metrics["task_type"] = normalized_task_type
        return self._advance_task(task, "plan", "planned")

    @mutating("task.approve")
    def approve_task(
        self,
        by: str,
        *,
        provenance: str = "audit",
        interactive_confirmed: bool = False,
        expected_subject_digest: str | None = None,
    ) -> dict[str, Any]:
        task = self._task_in_state("planned", "approve")
        if "plan" not in task:
            raise AnchorError("A recorded plan is required before approval.")
        snapshot = self._active_rules_snapshot()
        task["ruleset"] = snapshot
        approval_subject = self._task_approval_subject(task)
        subject_digest = self._document_digest(approval_subject)
        if provenance == "interactive-tty" and expected_subject_digest != subject_digest:
            raise AnchorError("The approval subject changed after it was displayed; review and confirm it again.")
        task["approval"] = {
            **self._approval_record(by, provenance, interactive_confirmed=interactive_confirmed),
            "plan_summary": task["plan"]["summary"],
            **self._task_approval_digests(approval_subject),
            "ruleset_version": snapshot["version"],
        }
        if provenance == "interactive-tty":
            task["approval"]["confirmed_subject_digest"] = subject_digest
        return self._advance_task(task, "approve", "approved")

    @consistent_read("task.approval-preview")
    def task_approval_preview(self) -> dict[str, Any]:
        """Return the exact task subject an interactive engineer must confirm."""

        task = deepcopy(self._task_in_state("planned", "approve"))
        if "plan" not in task:
            raise AnchorError("A recorded plan is required before approval.")
        task["ruleset"] = self._active_rules_snapshot()
        subject = self._task_approval_subject(task)
        return {
            "task_id": task["id"],
            "title": task["title"],
            "mode": task.get("mode", "FAST"),
            "plan_summary": task["plan"]["summary"],
            "subject_digest": self._document_digest(subject),
            "ruleset_version": task["ruleset"]["version"],
        }

    @mutating("task.verify")
    def verify_task(
        self,
        *,
        by: str,
        result: str,
        reason: str,
        provenance: str = "audit",
        interactive_confirmed: bool = False,
        recall: str | None = None,
        agent_turns: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        active_minutes: float | None = None,
        agent_provider: str | None = None,
        agent_model: str | None = None,
        expected_subject_digest: str | None = None,
    ) -> dict[str, Any]:
        normalized_result = self.validate_verification_result(result)
        engineer = self._required_text(by, "Engineer name")
        normalized_reason = self._required_text(reason, "Verification reason")
        normalized_recall = (
            self._required_text(recall, "Recall statement") if recall is not None else None
        )
        validated_metrics = self.validate_metric_types(
            agent_turns=agent_turns,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            active_minutes=active_minutes,
            agent_provider=agent_provider,
            agent_model=agent_model,
        )
        task = self._task_in_state("quality_checked", "verify")
        self._ensure_approval_matches_task(task)
        self._ensure_quality_matches_workspace(task)
        mode = str(task.get("mode", "FAST")).upper()
        if mode in {"STANDARD", "CAREFUL"} and normalized_recall is None:
            raise AnchorError(f"{mode} verification requires an engineer recall statement.")
        if normalized_recall is not None:
            task.setdefault("comprehension", {})["verification_check"] = {
                "statement": normalized_recall,
                "by": engineer,
                "at": self._timestamp(),
            }
        reported_metrics = {
            name: validated_metrics[name]
            for name in ("agent_turns", "input_tokens", "output_tokens", "active_minutes")
        }
        agent_identity = {
            name: validated_metrics[name]
            for name in ("agent_provider", "agent_model")
            if validated_metrics[name] is not None
        }
        if any(value is not None for value in reported_metrics.values()) or agent_identity:
            task.setdefault("metrics", {}).update(
                {
                    **{name: value for name, value in reported_metrics.items() if value is not None},
                    **agent_identity,
                    "provenance": "reported-at-verification",
                }
            )
        subject_digest = self._verification_subject_digest(
            task,
            result=normalized_result,
            reason=normalized_reason,
            recall=normalized_recall,
        )
        if provenance == "interactive-tty" and expected_subject_digest != subject_digest:
            raise AnchorError("The verification subject changed after it was displayed; review and confirm it again.")
        verification = {
            **self._approval_record(engineer, provenance, interactive_confirmed=interactive_confirmed),
            "result": normalized_result,
            "reason": normalized_reason,
        }
        if provenance == "interactive-tty":
            verification["confirmed_subject_digest"] = subject_digest
        task["verification"] = verification
        if normalized_result == "fail":
            self._append_task_event(task, "task.verify.failed")
            self._write_json(self.active_task_path, task)
            self._write_next_action(
                "Verification failed. Return to the smallest valid revision with one of:\n"
                f"{display_command('revise --target implement --reason <text>')}\n"
                f"{display_command('revise --target plan --reason <text>')}\n"
            )
            return task
        return self._advance_task(task, "verify", "verified")

    @consistent_read("task.verification-preview")
    def verification_preview(self, *, result: str, reason: str, recall: str | None) -> dict[str, Any]:
        normalized_result = self.validate_verification_result(result)
        normalized_reason = self._required_text(reason, "Verification reason")
        normalized_recall = (
            self._required_text(recall, "Recall statement") if recall is not None else None
        )
        task = self._task_in_state("quality_checked", "verify")
        self._ensure_approval_matches_task(task)
        self._ensure_quality_matches_workspace(task)
        digest = self._verification_subject_digest(
            task,
            result=normalized_result,
            reason=normalized_reason,
            recall=normalized_recall,
        )
        return {
            "task_id": task["id"],
            "title": task["title"],
            "result": normalized_result,
            "reason": normalized_reason,
            "subject_digest": digest,
        }

    @mutating("task.delayed-recall")
    def record_delayed_recall(
        self,
        *,
        task_id: str,
        by: str,
        response: str,
        score: int,
    ) -> dict[str, Any]:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise AnchorError("Invalid AnchorLoop task ID.")
        if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 5:
            raise AnchorError("Delayed recall score must be an integer from 0 to 5.")
        path = self.anchor_dir / "tasks" / "closed" / f"{task_id}.json"
        if not self._exists(path):
            raise AnchorError(f"Closed task '{task_id}' does not exist.")
        task = self._read_json(path)
        self.validate_task_schema(task)
        if task.get("id") != task_id or task.get("state") != "closed":
            raise AnchorError("Delayed recall requires an intact closed task record.")
        approval = task.get("approval")
        expected_approval = self._task_approval_digests(self._task_approval_subject(task))
        if (
            not isinstance(approval, dict)
            or approval.get("task_digest") != expected_approval["task_digest"]
        ):
            raise AnchorError(
                "Closed task ownership or recall policy changed after approval; delayed recall is blocked."
            )
        comprehension = task.get("comprehension")
        if not isinstance(comprehension, dict) or not comprehension.get("recall_due_at"):
            raise AnchorError("This task has no scheduled delayed recall.")
        if comprehension.get("delayed_recall") is not None:
            raise AnchorError("Delayed recall is already recorded for this task.")
        due_at = self._scheduled_recall_due_at(task)
        now = datetime.now(UTC)
        if now < due_at:
            raise AnchorError(f"Delayed recall is not due until {due_at.isoformat()}.")
        comprehension["delayed_recall"] = {
            "statement": self._required_text(response, "Delayed recall response"),
            "score": score,
            "by": self._required_text(by, "Engineer name"),
            "due_at": due_at.isoformat(),
            "recorded_at": now.isoformat(),
            "delay_seconds": max(0.0, (now - due_at).total_seconds()),
        }
        task.setdefault("metrics", {})["delayed_recall_score"] = score
        self._append_task_event(task, "task.delayed-recall.recorded")
        self._write_json(path, task)
        return task

    @mutating("task.outcome")
    def record_post_completion_outcome(
        self,
        *,
        task_id: str,
        by: str,
        defects_found: int,
        rollback: bool,
        corrective_refactor: bool,
        notes: str,
    ) -> dict[str, Any]:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise AnchorError("Invalid AnchorLoop task ID.")
        if (
            not isinstance(defects_found, int)
            or isinstance(defects_found, bool)
            or defects_found < 0
        ):
            raise AnchorError("Post-completion defects must be a non-negative integer.")
        if not isinstance(rollback, bool) or not isinstance(corrective_refactor, bool):
            raise AnchorError("Rollback and corrective-refactor outcomes must be boolean.")
        path = self.anchor_dir / "tasks" / "closed" / f"{task_id}.json"
        if not self._exists(path):
            raise AnchorError(f"Closed task '{task_id}' does not exist.")
        task = self._read_json(path)
        self.validate_task_schema(task)
        if task.get("id") != task_id or task.get("state") != "closed":
            raise AnchorError("Post-completion outcome requires an intact closed task record.")
        approval = task.get("approval")
        expected_approval = self._task_approval_digests(self._task_approval_subject(task))
        if (
            not isinstance(approval, dict)
            or approval.get("task_digest") != expected_approval["task_digest"]
        ):
            raise AnchorError(
                "Closed task ownership changed after approval; post-completion outcome is blocked."
            )
        record = {
            "at": self._timestamp(),
            "by": self._required_text(by, "Engineer name"),
            "defects_found": defects_found,
            "rollback": rollback,
            "corrective_refactor": corrective_refactor,
            "notes": self._required_text(notes, "Post-completion notes"),
            "provenance": "reported-post-completion",
        }
        task.setdefault("post_completion_outcomes", []).append(record)
        task.setdefault("metrics", {})["latest_post_completion_outcome"] = {
            key: record[key]
            for key in ("at", "defects_found", "rollback", "corrective_refactor")
        }
        self._append_task_event(task, "task.outcome.recorded")
        self._write_json(path, task)
        return task

    @consistent_read("report")
    def experiment_report(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        closed_directory = self.anchor_dir / "tasks" / "closed"
        for path in sorted(self.fs.glob(closed_directory, "*.json")):
            task = self._read_json(path)
            self.validate_task_schema(task)
            if task.get("state") != "closed" or task.get("id") != path.stem:
                raise AnchorError(f"Closed task record is inconsistent: {path}")
            metrics = task.get("metrics") if isinstance(task.get("metrics"), dict) else {}
            comprehension = (
                task.get("comprehension")
                if isinstance(task.get("comprehension"), dict)
                else {}
            )
            delayed = (
                comprehension.get("delayed_recall")
                if isinstance(comprehension.get("delayed_recall"), dict)
                else {}
            )
            outcomes = task.get("post_completion_outcomes")
            if not isinstance(outcomes, list):
                outcomes = []
            latest_outcome = outcomes[-1] if outcomes and isinstance(outcomes[-1], dict) else {}
            input_tokens = metrics.get("input_tokens")
            output_tokens = metrics.get("output_tokens")
            total_tokens = (
                input_tokens + output_tokens
                if isinstance(input_tokens, int) and isinstance(output_tokens, int)
                else None
            )
            rows.append(
                {
                    "task_id": task["id"],
                    "title": task.get("title"),
                    "mode": task.get("mode"),
                    "task_type": task.get("task_type"),
                    "verification_result": task.get("verification", {}).get("result"),
                    "wall_seconds": metrics.get("wall_seconds"),
                    "active_minutes": metrics.get("active_minutes"),
                    "agent_turns": metrics.get("agent_turns"),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "agent_provider": metrics.get("agent_provider"),
                    "agent_model": metrics.get("agent_model"),
                    "delayed_recall_score": delayed.get("score"),
                    "outcome_observations": len(outcomes),
                    "defects_found": latest_outcome.get("defects_found"),
                    "rollback": latest_outcome.get("rollback"),
                    "corrective_refactor": latest_outcome.get("corrective_refactor"),
                    "outcome_recorded_at": latest_outcome.get("at"),
                }
            )
        recall_scores = [
            row["delayed_recall_score"]
            for row in rows
            if isinstance(row.get("delayed_recall_score"), int)
        ]
        wall_times = [
            float(row["wall_seconds"])
            for row in rows
            if isinstance(row.get("wall_seconds"), (int, float))
            and math.isfinite(float(row["wall_seconds"]))
        ]
        return {
            "schema_version": 1,
            "generated_at": self._timestamp(),
            "summary": {
                "closed_tasks": len(rows),
                "tasks_with_delayed_recall": len(recall_scores),
                "tasks_with_outcome_observation": sum(
                    int(row["outcome_observations"] > 0) for row in rows
                ),
                "average_delayed_recall_score": (
                    sum(recall_scores) / len(recall_scores) if recall_scores else None
                ),
                "average_wall_seconds": (
                    sum(wall_times) / len(wall_times) if wall_times else None
                ),
            },
            "tasks": rows,
        }

    @mutating("task.revise")
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
            self._write_next_action(
                f"Revise the engineer-owned plan fields, then inspect: {display_command('plan --help')}\n"
            )
            return task

        task.setdefault("revisions", []).append(revision)
        task.pop("verification", None)
        task["state"] = "implementing"
        self._append_task_event(task, "task.revise.implement")
        self._write_json(self.active_task_path, task)
        self._write_next_action(f"{_next_action('implementing')}\n")
        return task

    @mutating("task.transition")
    def transition(self, action: str) -> dict[str, Any]:
        self.require_setup()
        if not self._exists(self.active_task_path):
            raise AnchorError(
                f"No active task. Run: {display_command(_START_TASK_ARGUMENTS)}"
            )
        task = self._read_json(self.active_task_path)
        self.validate_task_schema(task)
        state = task["state"]
        expected = TASK_TRANSITIONS.get(action, {})
        if state not in expected:
            allowed = ", ".join(name for name, states in TASK_TRANSITIONS.items() if state in states)
            detail = f" Allowed next command: {display_command(allowed)}." if allowed else ""
            raise AnchorError(f"Cannot run '{action}' while task is '{state}'.{detail}")
        if action in {"implement", "review", "precommit", "close"}:
            self._ensure_approval_matches_task(task)
        if action == "close":
            verification = task.get("verification", {})
            if verification.get("result") not in {"pass", "partial", "not-applicable"}:
                raise AnchorError("A recorded engineer verification is required before close.")
            self._ensure_quality_matches_workspace(task)
            task.setdefault("metrics", {})["closed_at"] = self._timestamp()
            try:
                created_at = datetime.fromisoformat(task["created_at"])
                closed_at = datetime.fromisoformat(task["metrics"]["closed_at"])
                task["metrics"]["wall_seconds"] = max(0.0, (closed_at - created_at).total_seconds())
            except (KeyError, TypeError, ValueError):
                task["metrics"]["wall_seconds"] = None
        task["state"] = expected[state]
        if action == "close" and task.get("mode") == "CAREFUL":
            comprehension = task.get("comprehension")
            if not isinstance(comprehension, dict):
                raise AnchorError("CAREFUL tasks require a delayed-recall policy before close.")
            # New records carry the approved delay policy and derive their due
            # time only at close.  A pre-policy record instead binds the
            # timestamp it was originally approved with; leave that legacy
            # evidence intact so an upgrade cannot invalidate its approval.
            if "recall_delay_hours" in comprehension:
                closed_at = self._closed_at(task)
                delay = self._recall_delay_hours(comprehension)
                comprehension["recall_due_at"] = (closed_at + timedelta(hours=delay)).isoformat()
        self._append_task_event(task, f"task.{action}")
        if action == "close":
            closed_path = self.anchor_dir / "tasks" / "closed" / f"{task['id']}.json"
            self._write_json(closed_path, task)
            self._unlink(self.active_task_path)
            recall_due_at = (
                task.get("comprehension", {}).get("recall_due_at")
                if isinstance(task.get("comprehension"), dict)
                else None
            )
            recall_guidance = ""
            if recall_due_at:
                recall_command = display_command(
                    f"recall --task {task['id']} --by <engineer> --response <text> --score 0..5"
                )
                recall_guidance = (
                    f"Delayed recall is scheduled for {recall_due_at}. When due, run: "
                    f"{recall_command}\n"
                )
            self._write_next_action(
                recall_guidance
                + f"No active task. Start the next one with: {display_command(_START_TASK_ARGUMENTS)}\n"
            )
            return task
        self._write_json(self.active_task_path, task)
        self._write_next_action(f"{_next_action(task['state'])}\n")
        return task

    @mutating("task.precommit")
    def precommit(self) -> dict[str, Any]:
        self.require_setup()
        if not self._exists(self.active_task_path):
            raise AnchorError(
                f"No active task. Run: {display_command(_START_TASK_ARGUMENTS)}"
            )
        task = self._read_json(self.active_task_path)
        self.validate_task_schema(task)
        if task["state"] != "review_ready":
            raise AnchorError(f"Cannot run 'precommit' while task is '{task['state']}'.")
        self._ensure_approval_matches_task(task)
        ruleset = task.get("ruleset") or {"rules": {}}
        quality = run_precommit(self.root, active_categories=set(ruleset["rules"]))
        task.setdefault("quality", []).append(quality)
        self._write_json(self.active_task_path, task)
        if quality["status"] == "blocked":
            locations = ", ".join(finding["location"] for finding in quality["findings"])
            raise StateRecordedError(f"Pre-commit is blocked. Fix findings before verification: {locations}")
        return self.transition("precommit")

    @mutating("rule.propose")
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

    @mutating("rule.approve")
    def approve_rule(
        self,
        rule_id: str,
        *,
        by: str,
        provenance: str = "audit",
        interactive_confirmed: bool = False,
        expected_subject_digest: str | None = None,
    ) -> dict[str, Any]:
        self.require_setup()
        proposal_path = self._rule_proposal_path(rule_id)
        if not self._exists(proposal_path):
            raise AnchorError(f"Rule proposal '{rule_id}' does not exist.")
        rule = self._read_json(proposal_path)
        self._validate_rule_document(rule, expected_id=rule_id, expected_status="proposed")
        subject_digest = self._document_digest(rule)
        if provenance == "interactive-tty" and expected_subject_digest != subject_digest:
            raise AnchorError("The rule proposal changed after it was displayed; review and confirm it again.")
        rule["status"] = "approved"
        rule["approval"] = self._approval_record(
            by,
            provenance,
            interactive_confirmed=interactive_confirmed,
        )
        if provenance == "interactive-tty":
            rule["approval"]["confirmed_subject_digest"] = subject_digest
        rule["approved_at"] = rule["approval"]["at"]
        rule["approved_document_digest"] = self._approved_rule_document_digest(rule)
        approved_path = self.anchor_dir / "rules" / "approved" / proposal_path.name
        active = self._active_rules_with(rule)
        self._write_json(approved_path, rule)
        self._write_json(self.anchor_dir / "rules" / "active.json", active)
        config = self._read_json(self.config_path)
        self._refresh_config_ruleset_metadata(config)
        self._write_json(self.config_path, config)
        self._unlink(proposal_path)
        self._append_event({"type": "rule.approved", "rule_id": rule_id, "at": self._timestamp()})
        return rule

    @consistent_read("rule.approval-preview")
    def rule_approval_preview(self, rule_id: str) -> dict[str, Any]:
        self.require_setup()
        proposal_path = self._rule_proposal_path(rule_id)
        if not self._exists(proposal_path):
            raise AnchorError(f"Rule proposal '{rule_id}' does not exist.")
        rule = self._read_json(proposal_path)
        self._validate_rule_document(rule, expected_id=rule_id, expected_status="proposed")
        return {
            "rule_id": rule_id,
            "category": rule["category"],
            "wording": rule["wording"],
            "subject_digest": self._document_digest(rule),
        }

    @mutating("rule.supersede")
    def supersede_rule(
        self,
        *,
        old_rule_id: str,
        new_rule_id: str,
        by: str,
        reason: str,
        provenance: str = "audit",
        interactive_confirmed: bool = False,
        expected_subject_digest: str | None = None,
    ) -> dict[str, Any]:
        self.require_setup()
        self._validate_rule_id(old_rule_id)
        self._validate_rule_id(new_rule_id)
        if old_rule_id == new_rule_id:
            raise AnchorError("A rule cannot supersede itself.")
        old_rule_path = self._rule_approved_path(old_rule_id)
        new_rule_path = self._rule_approved_path(new_rule_id)
        if not self._exists(old_rule_path) or not self._exists(new_rule_path):
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
        active = self._read_json(active_path) if self._exists(active_path) else {"version": 1, "rules": {}}
        category = old_rule["category"]
        if active["rules"].get(category) != old_rule_id:
            raise AnchorError(f"Rule '{old_rule_id}' is not the active {category} rule.")
        subject_digest = self._rule_supersession_subject_digest(
            old_rule,
            new_rule,
            active,
            reason=reason,
        )
        if provenance == "interactive-tty" and expected_subject_digest != subject_digest:
            raise AnchorError("The rule supersession subject changed after it was displayed; review and confirm it again.")
        approval = self._approval_record(
            by,
            provenance,
            interactive_confirmed=interactive_confirmed,
        )
        if provenance == "interactive-tty":
            approval["confirmed_subject_digest"] = subject_digest
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

    @consistent_read("rule.supersession-preview")
    def rule_supersession_preview(
        self,
        *,
        old_rule_id: str,
        new_rule_id: str,
        reason: str,
    ) -> dict[str, Any]:
        self.require_setup()
        old_rule = self._read_json(self._rule_approved_path(old_rule_id))
        new_rule = self._read_json(self._rule_approved_path(new_rule_id))
        active_path = self.anchor_dir / "rules" / "active.json"
        active = self._read_json(active_path) if self._exists(active_path) else {"version": 1, "rules": {}}
        digest = self._rule_supersession_subject_digest(old_rule, new_rule, active, reason=reason)
        return {
            "old_rule_id": old_rule_id,
            "new_rule_id": new_rule_id,
            "reason": self._required_text(reason, "Supersession reason"),
            "subject_digest": digest,
        }

    @consistent_read("rules.list")
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

    @consistent_read("agent.detect")
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

    @consistent_read("agent.status")
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
            f"From {self.root}, apply with: {display_command('agent setup portable --apply')}",
        ]

    @mutating("agent.setup")
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
        active = self._read_json(path) if self._exists(path) else {"version": 1, "rules": {}}
        existing = active["rules"].get(rule["category"])
        if not existing:
            active["rules"][rule["category"]] = rule["id"]
        return active

    def _active_rules_snapshot(self) -> dict[str, Any]:
        path = self.anchor_dir / "rules" / "active.json"
        active = self._read_json(path) if self._exists(path) else {"version": 1, "rules": {}}
        rules = dict(active["rules"])
        documents = {}
        for category, rule_id in sorted(rules.items()):
            approved_path = self._rule_approved_path(rule_id)
            if not self._exists(approved_path):
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
        if self._exists(self.active_task_path):
            task = self._read_json(self.active_task_path)
            return f"Existing task: {task['title']} ({task['state']}).\n{_next_action(task['state'])}\n"
        return (
            "Anchor is already configured. Start a task with: "
            f"{display_command(_START_TASK_ARGUMENTS)}\n"
        )

    def _task_in_state(self, state: str, action: str) -> dict[str, Any]:
        return self._task_in_states({state}, action)

    def _task_in_states(self, states: set[str], action: str) -> dict[str, Any]:
        self.require_setup()
        if not self._exists(self.active_task_path):
            raise AnchorError(
                f"No active task. Run: {display_command(_START_TASK_ARGUMENTS)}"
            )
        task = self._read_json(self.active_task_path)
        self.validate_task_schema(task)
        if task["state"] not in states:
            raise AnchorError(f"Cannot run '{action}' while task is '{task['state']}'.")
        return task

    def _advance_task(self, task: dict[str, Any], action: str, state: str) -> dict[str, Any]:
        task["state"] = state
        self._append_task_event(task, f"task.{action}")
        self._write_json(self.active_task_path, task)
        self._write_next_action(f"{_next_action(state)}\n")
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
            if any(any(self.root.glob(pattern)) for pattern in patterns):
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
        self.validate_task_schema(task)
        event = {"type": event_type, "at": self._timestamp(), "state": task["state"]}
        task["events"].append(event)
        self._append_event({"task_id": task["id"], **event})

    def _append_event(self, event: dict[str, Any]) -> None:
        if self._mutation_depth:
            self._staged_events.append(deepcopy(event))
            return
        raise AnchorError("Anchor events must be emitted inside a project transaction.")

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
        current = self._read_text(path).splitlines() if self._exists(path) else []
        additions = [line for line in required_lines if line not in current]
        if additions:
            prefix = "\n" if current else ""
            self._write_text(path, "\n".join(current) + prefix + "\n".join(additions) + "\n")

    def _ensure_project_gitignore(self) -> None:
        path = self.root / ".gitignore"
        required_lines = (
            "/cache/",
            "/.cache/",
            "/.anchor/cache/",
            "/.npm/",
            "/.npm-cache/",
            "graphify-out/",
            "__pycache__/",
            "*.py[cod]",
        )
        current = self._read_text(path) if self._exists(path) else ""
        existing_lines = set(current.splitlines())
        additions = [line for line in required_lines if line not in existing_lines]
        if not additions:
            return
        separator = "" if not current or current.endswith(("\n", "\r")) else "\n"
        self._write_text(path, current + separator + "\n".join(additions) + "\n")

    def _ensure_anchor_gitignore(self) -> None:
        path = self.anchor_dir / ".gitignore"
        required_lines = (
            "cache/",
            "logs/",
            "graphify/query-history.jsonl",
            "project.lock",
            "transactions/",
            "outbox/",
        )
        current = self._read_text(path) if self._exists(path) else ""
        existing_lines = set(current.splitlines())
        additions = [line for line in required_lines if line not in existing_lines]
        if not additions:
            return
        separator = "" if not current or current.endswith(("\n", "\r")) else "\n"
        self._write_text(path, current + separator + "\n".join(additions) + "\n")

    def _write_next_action(self, content: str) -> None:
        self._write_text(self.next_action_path, content)

    def next_action(self) -> str:
        return self._read_text(self.next_action_path).strip()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    @staticmethod
    def _mode_rank(mode: str) -> int:
        return {"FAST": 0, "STANDARD": 1, "CAREFUL": 2}[mode]

    @staticmethod
    def _recommended_mode(
        task_type: str,
        brief: dict[str, Any],
        *,
        title: str | None = None,
        approved_rules: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Recommend a minimum ownership mode from explicit, inspectable signals.

        This is a recommendation, never a destructive inference: unknown work
        remains STANDARD and a lower selected mode still requires an engineer's
        recorded override reason.
        """

        task_text = AnchorProject._required_text(task_type, "Task type")
        normalized_brief = AnchorProject.validate_brief_fields(brief)
        text = " ".join(
            part
            for part in [task_text, title or "", *(value or "" for value in normalized_brief.values())]
            if part
        ).casefold()
        path_text = "/" + text.replace("\\", "/")
        signals: list[str] = []
        for label, aliases in _CAREFUL_TEXT_SIGNALS.items():
            if any(alias.casefold() in text for alias in aliases):
                signals.append(label)
        for label, markers in _CAREFUL_PATH_SIGNALS.items():
            if any(marker.casefold() in path_text for marker in markers):
                signals.append(label)
        for category, document in sorted((approved_rules or {}).items()):
            if not isinstance(document, dict):
                continue
            wording = document.get("wording")
            if not isinstance(wording, str):
                continue
            rule_text = wording.casefold()
            explicit_careful = "careful" in rule_text and any(
                marker in rule_text
                for marker in ("require", "required", "must", "risk:", "risk=", "требует", "обязател")
            )
            explicit_russian_careful = any(
                marker in rule_text
                for marker in ("риск: careful", "риск=careful", "режим: careful", "режим=careful")
            )
            if explicit_careful or explicit_russian_careful:
                signals.append(f"approved {category} rule")
        if signals:
            return "CAREFUL", f"risk signal: {', '.join(sorted(set(signals)))}"
        if task_text.casefold() in {"docs", "chore", "документация", "документы", "рутина"}:
            return "FAST", f"task type {task_type!r} is normally low-risk and reversible"
        if task_text.casefold() != "general":
            return "STANDARD", f"task type {task_type!r} changes product or code behavior"
        return "STANDARD", "unknown task risk defaults to engineer-owned STANDARD planning"

    @contextmanager
    def _mutation(self, command: str, *, allow_unconfigured: bool) -> Iterator[None]:
        if self._mutation_depth:
            self._mutation_depth += 1
            try:
                yield
            finally:
                self._mutation_depth -= 1
            return

        if not allow_unconfigured:
            self.require_setup()
        with ProjectLock(self.root, purpose=command):
            manager = TransactionManager(self.root)
            recovery = manager.recover()
            if recovery.performed_work:
                recovered = [
                    f"{item.transaction_id} ({item.command or 'unknown command'})"
                    for item in recovery.transactions
                ]
                detail = ", ".join(recovered)
                if recovery.delivered_events and not detail:
                    detail = f"{recovery.delivered_events} durable event(s)"
                if not detail:
                    detail = "durable recovery work"
                raise AnchorError(
                    f"AnchorLoop recovered {detail} before '{command}'. To avoid duplicating an "
                    f"interrupted mutation, '{command}' was not run. Inspect the recovered state with "
                    f"{display_command('status')}, then rerun the command explicitly only if it is "
                    "still intended."
                )
            self._transaction_manager = manager
            self._staged_files = {}
            self._staged_events = []
            self._mutation_depth = 1
            try:
                try:
                    yield
                except StateRecordedError:
                    self._commit_staged(command)
                    raise
                else:
                    self._commit_staged(command)
            finally:
                self._mutation_depth = 0
                self._transaction = None
                self._transaction_manager = None
                self._staged_files = {}
                self._staged_events = []

    @contextmanager
    def _consistent_read(self, command: str) -> Iterator[None]:
        if self._mutation_depth:
            yield
            return
        self.require_setup()
        with ProjectLock(self.root, purpose=command):
            health = TransactionManager(self.root).inspect()
            if health.pending_transactions or health.outbox_events:
                raise AnchorError(
                    "AnchorLoop recovery is pending. Inspect with: "
                    f"{display_command('doctor --strict')}; repair with: "
                    f"{display_command('doctor --repair')}"
                )
            yield

    def _commit_staged(self, command: str) -> None:
        if not self._staged_files and not self._staged_events:
            return
        if self._transaction_manager is None:
            raise AnchorError("Anchor mutation has no transaction manager.")
        transaction = self._transaction_manager.begin(command=command)
        self._transaction = transaction
        writes = sorted(
            ((path, content) for path, content in self._staged_files.items() if content is not None),
            key=lambda item: item[0].as_posix(),
        )
        deletes = sorted(
            (path for path, content in self._staged_files.items() if content is None),
            key=lambda path: path.as_posix(),
        )
        for path, content in writes:
            transaction.write_bytes(path, content)
        for path in deletes:
            transaction.delete(path)
        for event in self._staged_events:
            transaction.emit_event(event)
        transaction.commit()

    def _exists(self, path: Path) -> bool:
        candidate = self.fs.validate(path)
        if self._mutation_depth and candidate in self._staged_files:
            return self._staged_files[candidate] is not None
        return self.fs.exists(candidate)

    def _read_bytes(self, path: Path) -> bytes:
        candidate = self.fs.validate(path)
        if self._mutation_depth and candidate in self._staged_files:
            content = self._staged_files[candidate]
            if content is None:
                raise AnchorError(f"Managed path does not exist: {candidate}")
            return content
        return self.fs.read_bytes(candidate)

    def _read_text(self, path: Path) -> str:
        try:
            return self._read_bytes(path).decode("utf-8")
        except UnicodeDecodeError as error:
            raise AnchorError(f"Cannot decode managed file: {path}") from error

    def _unlink(self, path: Path, *, missing_ok: bool = False) -> None:
        candidate = self.fs.validate(path)
        if not self._exists(candidate):
            if missing_ok:
                return
            raise AnchorError(f"Managed path does not exist: {candidate}")
        if self._mutation_depth:
            self._staged_files[candidate] = None
            return
        self.fs.unlink(candidate, missing_ok=missing_ok)

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(self._read_text(path))
        except (AnchorError, UnicodeDecodeError) as error:
            raise AnchorError(f"Cannot read Anchor state at {path}.") from error
        except json.JSONDecodeError as error:
            raise AnchorError(
                f"Anchor state is invalid JSON at {path}. Run: {display_command('doctor')}"
            ) from error
        if not isinstance(data, dict):
            raise AnchorError(
                f"Anchor state at {path} must be a JSON object. Run: {display_command('doctor')}"
            )
        return data

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        candidate = self.fs.validate(path)
        closed_tasks = self.anchor_dir / "tasks" / "closed"
        if candidate == self.active_task_path or candidate.parent == closed_tasks:
            self.validate_task_schema(data)
        self._write_text(path, json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")

    def _write_json_if_missing(self, path: Path, data: dict[str, Any]) -> None:
        if not self._exists(path):
            self._write_json(path, data)

    def _write_text(self, path: Path, content: str) -> None:
        candidate = self.fs.validate(path)
        if self._mutation_depth:
            self._staged_files[candidate] = content.encode("utf-8")
            return
        self.fs.atomic_write_text(candidate, content)

    def _write_text_if_missing(self, path: Path, content: str) -> None:
        if not self._exists(path):
            self._write_text(path, content)

    @staticmethod
    def _required_text(value: object, label: str) -> str:
        if not isinstance(value, str):
            raise AnchorError(f"{label} must be text.")
        normalized = value.strip()
        if not normalized:
            raise AnchorError(f"{label} cannot be empty.")
        return normalized

    @classmethod
    def validate_brief_fields(
        cls,
        values: object,
        *,
        allow_unfilled: bool = False,
    ) -> dict[str, str | None]:
        """Validate the complete brief shape at the domain boundary.

        Argparse already collects these fields for the CLI, but AnchorProject is
        a public API too.  Accepting a partial dictionary here would create a
        task that cannot safely pass through the rest of the workflow.
        """

        if not isinstance(values, dict):
            raise AnchorError("Engineer brief must be an object with every required field.")
        keys = set(values)
        expected = set(BRIEF_FIELDS)
        missing = sorted(expected - keys)
        unexpected = sorted(str(key) for key in keys - expected)
        if missing or unexpected:
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if unexpected:
                details.append(f"unexpected: {', '.join(unexpected)}")
            raise AnchorError(f"Engineer brief fields must be exact ({'; '.join(details)}).")
        normalized: dict[str, str | None] = {}
        for field in BRIEF_FIELDS:
            value = values[field]
            if value is None and allow_unfilled:
                normalized[field] = None
                continue
            normalized[field] = cls._required_text(value, f"Engineer brief field '{field}'")
        return normalized

    @staticmethod
    def validate_verification_result(result: object) -> str:
        if not isinstance(result, str) or result not in VERIFICATION_RESULTS:
            options = ", ".join(sorted(VERIFICATION_RESULTS))
            raise AnchorError(f"Verification result must be one of: {options}.")
        return result

    @classmethod
    def validate_metric_types(
        cls,
        *,
        agent_turns: object = None,
        input_tokens: object = None,
        output_tokens: object = None,
        active_minutes: object = None,
        agent_provider: object = None,
        agent_model: object = None,
    ) -> dict[str, int | float | str | None]:
        """Validate reported metrics without coercing public API inputs."""

        integer_metrics = {
            "agent_turns": agent_turns,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        validated: dict[str, int | float | str | None] = {}
        for name, value in integer_metrics.items():
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise AnchorError(f"Metric {name} must be a non-negative integer.")
            validated[name] = value
        if active_minutes is not None:
            if (
                not isinstance(active_minutes, (int, float))
                or isinstance(active_minutes, bool)
                or not math.isfinite(float(active_minutes))
                or active_minutes < 0
            ):
                raise AnchorError("Metric active_minutes must be a finite non-negative number.")
        validated["active_minutes"] = active_minutes
        if (agent_provider is None) != (agent_model is None):
            raise AnchorError("Agent provider and model must be reported together.")
        validated["agent_provider"] = (
            cls._required_text(agent_provider, "Agent provider")
            if agent_provider is not None
            else None
        )
        validated["agent_model"] = (
            cls._required_text(agent_model, "Agent model")
            if agent_model is not None
            else None
        )
        return validated

    @classmethod
    def validate_task_schema(cls, task: object) -> None:
        """Reject malformed task state before it can be staged or advanced."""

        if not isinstance(task, dict):
            raise AnchorError("Anchor task state must be a JSON object.")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            raise AnchorError("Anchor task has an invalid ID.")
        cls._required_text(task.get("title"), "Task title")
        state = task.get("state")
        allowed_states = {*NEXT_ACTIONS, "closed"}
        if state not in allowed_states:
            raise AnchorError(f"Anchor task has an invalid state: {state!r}.")
        cls._required_text(task.get("created_at"), "Task creation time")
        brief = cls.validate_brief_fields(task.get("brief"), allow_unfilled=True)
        brief_record = task.get("brief_record")
        brief_is_complete = all(value is not None for value in brief.values())
        if brief_record is not None:
            if not isinstance(brief_record, dict):
                raise AnchorError("Anchor task brief record must be an object.")
            for field in ("by", "at", "brief_digest"):
                cls._required_text(brief_record.get(field), f"Anchor task brief record {field}")
            if not brief_is_complete:
                raise AnchorError("Anchor task has a brief record without a complete brief.")
        if state != "briefing" and not brief_is_complete:
            raise AnchorError("Anchor task cannot leave briefing with an incomplete brief.")
        events = task.get("events")
        if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
            raise AnchorError("Anchor task events must be a list of objects.")

        planned_states = {
            "planned",
            "approved",
            "implementing",
            "review_ready",
            "quality_checked",
            "verified",
            "closed",
        }
        if state not in planned_states:
            return
        if brief_record is None:
            raise AnchorError("Anchor task cannot leave briefing without a recorded brief.")
        mode = task.get("mode")
        if mode not in TASK_MODES:
            raise AnchorError("Anchor task has an invalid ownership mode.")
        cls._required_text(task.get("task_type"), "Task type")
        plan = task.get("plan")
        if not isinstance(plan, dict):
            raise AnchorError("Anchor task plan must be an object.")
        for field in ("summary", "approach", "rejected_alternative", "primary_risk", "verification_strategy"):
            cls._required_text(plan.get(field), f"Anchor task plan {field}")
        comprehension = task.get("comprehension")
        if not isinstance(comprehension, dict):
            raise AnchorError("Anchor task comprehension policy must be an object.")
        if mode == "CAREFUL":
            if "recall_delay_hours" in comprehension:
                delay = comprehension.get("recall_delay_hours")
                if (
                    not isinstance(delay, int)
                    or isinstance(delay, bool)
                    or delay != CAREFUL_RECALL_DELAY_HOURS
                ):
                    raise AnchorError(
                        "CAREFUL tasks must retain the approved 24-hour delayed-recall policy."
                    )
            elif comprehension.get("recall_due_at") is None:
                raise AnchorError(
                    "Legacy CAREFUL tasks must retain their approved delayed-recall timestamp."
                )
        elif comprehension.get("recall_delay_hours") is not None:
            raise AnchorError("Only CAREFUL tasks may carry a delayed-recall policy.")
        due_at = comprehension.get("recall_due_at")
        if due_at is not None:
            cls._required_text(due_at, "Delayed recall due time")
        if state in {"verified", "closed"}:
            verification = task.get("verification")
            if not isinstance(verification, dict):
                raise AnchorError("Verified tasks require a verification record.")
            cls.validate_verification_result(verification.get("result"))
            cls._required_text(verification.get("reason"), "Verification reason")

    @staticmethod
    def _closed_at(task: dict[str, Any]) -> datetime:
        metrics = task.get("metrics")
        value = metrics.get("closed_at") if isinstance(metrics, dict) else None
        if not isinstance(value, str):
            raise AnchorError("Closed CAREFUL task is missing its close timestamp.")
        try:
            closed_at = datetime.fromisoformat(value)
        except ValueError as error:
            raise AnchorError("Closed CAREFUL task has an invalid close timestamp.") from error
        if closed_at.tzinfo is None:
            raise AnchorError("Closed CAREFUL task timestamp must include a timezone.")
        return closed_at

    @staticmethod
    def _recall_delay_hours(comprehension: dict[str, Any]) -> int:
        delay = comprehension.get("recall_delay_hours")
        if (
            not isinstance(delay, int)
            or isinstance(delay, bool)
            or delay != CAREFUL_RECALL_DELAY_HOURS
        ):
            raise AnchorError(
                "Delayed recall requires the approved 24-hour CAREFUL policy."
            )
        return delay

    def _scheduled_recall_due_at(self, task: dict[str, Any]) -> datetime:
        """Return an approval-bound due time and validate the current policy when present."""

        comprehension = task.get("comprehension")
        if not isinstance(comprehension, dict):
            raise AnchorError("Delayed recall policy is missing or invalid.")
        stored_due_at = comprehension.get("recall_due_at")
        if not isinstance(stored_due_at, str):
            raise AnchorError("Delayed recall schedule is missing. Close the task before recording recall.")
        try:
            due_at = datetime.fromisoformat(stored_due_at)
        except ValueError as error:
            raise AnchorError(
                "Delayed recall schedule is invalid. Run: "
                f"{display_command('doctor --strict')}"
            ) from error
        if due_at.tzinfo is None:
            raise AnchorError("Delayed recall schedule must include a timezone.")
        # Records written before the close-relative policy had only the
        # approval-bound timestamp.  They cannot prove a close-relative delay,
        # but their digest still protects that historical timestamp from edits.
        if "recall_delay_hours" not in comprehension:
            approval = task.get("approval")
            expected_approval = self._task_approval_digests(self._task_approval_subject(task))
            if (
                not isinstance(approval, dict)
                or approval.get("task_digest") != expected_approval["task_digest"]
            ):
                raise AnchorError(
                    "Legacy delayed recall schedule changed after approval. Run: "
                    f"{display_command('doctor --strict')}"
                )
            return due_at
        delay = self._recall_delay_hours(comprehension)
        expected_due_at = self._closed_at(task) + timedelta(hours=delay)
        if due_at != expected_due_at:
            raise AnchorError(
                "Delayed recall schedule does not match the approved 24-hour policy and close time. "
                f"Run: {display_command('doctor --strict')}"
            )
        return due_at


    @staticmethod
    def _document_digest(document: Any) -> str:
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _task_approval_subject(task: dict[str, Any]) -> dict[str, Any]:
        comprehension = task.get("comprehension")
        # New records bind the immutable delay policy, not a timestamp that is
        # intentionally assigned only when the task closes. Preserve the old
        # shape for legacy records so their existing approval remains
        # inspectable rather than silently changing its digest.
        if isinstance(comprehension, dict) and "recall_delay_hours" in comprehension:
            comprehension_policy: dict[str, Any] | None = {
                "baseline": comprehension.get("baseline"),
                "recall_delay_hours": comprehension.get("recall_delay_hours"),
            }
        elif isinstance(comprehension, dict):
            comprehension_policy = {
                "baseline": comprehension.get("baseline"),
                "recall_due_at": comprehension.get("recall_due_at"),
            }
        else:
            comprehension_policy = None
        return {
            "task_id": task.get("id"),
            "title": task.get("title"),
            "mode": task.get("mode"),
            "task_type": task.get("task_type"),
            "brief": task.get("brief"),
            "brief_record": task.get("brief_record"),
            "plan": task.get("plan"),
            "human_artifact": task.get("human_artifact"),
            "comprehension_policy": comprehension_policy,
            "ruleset": task.get("ruleset"),
        }

    def _task_approval_digests(self, subject: dict[str, Any]) -> dict[str, str]:
        return {
            "brief_digest": self._document_digest(subject["brief"]),
            "brief_record_digest": self._document_digest(subject["brief_record"]),
            "plan_digest": self._document_digest(subject["plan"]),
            "ownership_digest": self._document_digest(
                {
                    "mode": subject["mode"],
                    "task_type": subject["task_type"],
                    "human_artifact": subject["human_artifact"],
                    "comprehension_policy": subject["comprehension_policy"],
                }
            ),
            "ruleset_digest": self._document_digest(subject["ruleset"]),
            "task_digest": self._document_digest(subject),
        }

    def _verification_subject_digest(
        self,
        task: dict[str, Any],
        *,
        result: str,
        reason: str,
        recall: str | None,
    ) -> str:
        quality = task.get("quality", [])
        latest_quality = quality[-1] if quality else None
        subject = {
            "task_id": task.get("id"),
            "approval_digest": task.get("approval", {}).get("task_digest"),
            "quality_fingerprint": (
                latest_quality.get("workspace_fingerprint")
                if isinstance(latest_quality, dict)
                else None
            ),
            "result": result,
            "reason": self._required_text(reason, "Verification reason"),
            "recall": recall.strip() if isinstance(recall, str) else None,
        }
        return self._document_digest(subject)

    def _rule_supersession_subject_digest(
        self,
        old_rule: dict[str, Any],
        new_rule: dict[str, Any],
        active: dict[str, Any],
        *,
        reason: str,
    ) -> str:
        return self._document_digest(
            {
                "old_rule_id": old_rule.get("id"),
                "old_rule_digest": old_rule.get("approved_document_digest"),
                "new_rule_id": new_rule.get("id"),
                "new_rule_digest": new_rule.get("approved_document_digest"),
                "active_rules": active.get("rules"),
                "reason": self._required_text(reason, "Supersession reason"),
            }
        )

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
            next_action = (
                "The approved plan or ruleset changed. Review it, then run: "
                f"{display_command('approve --by <engineer>')}"
            )
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
        raise StateRecordedError(next_action)

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
            raise StateRecordedError(
                "The latest quality result has no workspace fingerprint. "
                "The task returned to review_ready; rerun: "
                f"{display_command('precommit')}"
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
        raise StateRecordedError("Code changed after the quality gate. The task returned to review_ready.")

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
            "Quality evidence was invalidated. Review the current diff and rerun: "
            f"{display_command('precommit')}\n"
        )
