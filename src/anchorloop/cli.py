from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .project import AnchorError, AnchorProject, TASK_TRANSITIONS
from .skill_install import SUPPORTED_PLATFORMS, SkillInstaller


def _path_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", default=".", help="Project root (default: current directory)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anchor",
        description="AnchorLoop: engineer-controlled, agent-neutral AI coding workflow.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("init", "add"):
        command = commands.add_parser(name, help=f"Preview or apply Anchor {name} setup")
        if name == "init":
            command.add_argument("name", nargs="?", help="New project directory name")
        _path_argument(command)
        command.add_argument("--apply", action="store_true", help="Apply the shown setup plan")

    workflow_commands: dict[str, argparse.ArgumentParser] = {}
    for name in (
        "help",
        "status",
        "doctor",
        "plan",
        "approve",
        "implement",
        "review",
        "precommit",
        "verify",
        "revise",
        "close",
    ):
        command = commands.add_parser(name)
        _path_argument(command)
        workflow_commands[name] = command

    workflow_commands["plan"].add_argument("--summary", required=True, help="Concrete plan prepared for engineer approval")
    workflow_commands["approve"].add_argument("--by", required=True, help="Engineer approving the recorded plan")
    workflow_commands["approve"].add_argument(
        "--provenance",
        choices=("audit", "interactive-tty"),
        default="audit",
        help="How the approval was captured; audit is not an authentication boundary",
    )
    workflow_commands["verify"].add_argument("--by", required=True, help="Engineer who performed manual verification")
    workflow_commands["verify"].add_argument("--result", required=True, choices=("pass", "fail", "partial", "not-applicable"))
    workflow_commands["verify"].add_argument("--reason", required=True, help="Observed verification outcome or accepted limitation")
    workflow_commands["verify"].add_argument(
        "--provenance",
        choices=("audit", "interactive-tty"),
        default="audit",
        help="How the verification was captured; audit is not an authentication boundary",
    )
    workflow_commands["revise"].add_argument("--target", required=True, choices=("implement", "plan"))
    workflow_commands["revise"].add_argument("--reason", required=True)

    start = commands.add_parser("start", help="Create an engineer-owned task")
    start.add_argument("title")
    _path_argument(start)

    brief = commands.add_parser("brief", help="Record the engineer task brief before planning")
    brief.add_argument("--by", required=True, help="Engineer who owns the task brief")
    brief.add_argument("--outcome", required=True)
    brief.add_argument("--scope", required=True)
    brief.add_argument("--constraints", required=True)
    brief.add_argument("--invariant", required=True)
    brief.add_argument("--uncertainty", required=True)
    _path_argument(brief)

    rules = commands.add_parser("rules", help="Inspect and approve project rules")
    rule_commands = rules.add_subparsers(dest="rule_command", required=True)
    rule_list = rule_commands.add_parser("list")
    _path_argument(rule_list)
    rule_propose = rule_commands.add_parser("propose")
    rule_propose.add_argument("category", choices=("code-quality", "security", "structure"))
    rule_propose.add_argument("wording")
    _path_argument(rule_propose)
    rule_approve = rule_commands.add_parser("approve")
    rule_approve.add_argument("rule_id")
    rule_approve.add_argument("--by", required=True, help="Engineer approving the exact rule document")
    rule_approve.add_argument("--provenance", choices=("audit", "interactive-tty"), default="audit")
    _path_argument(rule_approve)
    rule_supersede = rule_commands.add_parser("supersede")
    rule_supersede.add_argument("old_rule_id")
    rule_supersede.add_argument("new_rule_id")
    rule_supersede.add_argument("--by", required=True, help="Engineer authorizing the replacement")
    rule_supersede.add_argument("--reason", required=True)
    rule_supersede.add_argument("--provenance", choices=("audit", "interactive-tty"), default="audit")
    _path_argument(rule_supersede)

    for name in ("install", "uninstall"):
        command = commands.add_parser(
            name,
            help=f"Preview or {name} the portable AnchorLoop skill adapter",
        )
        command.add_argument("--project", action="store_true", help="Use the current project's skill directory")
        command.add_argument("--platform", choices=SUPPORTED_PLATFORMS, default="agents")
        command.add_argument("--apply", action="store_true", help=f"Apply the shown {name} operation")
        command.add_argument(
            "--force",
            action="store_true",
            help=(
                "Allow overwriting or removing modified skill assets"
                if name == "install"
                else "Remove modified skill assets owned by the installer"
            ),
        )
        _path_argument(command)

    agent = commands.add_parser("agent", help="Inspect host-agent integration capabilities")
    agent_commands = agent.add_subparsers(dest="agent_command", required=True)
    for name in ("detect", "status"):
        command = agent_commands.add_parser(name)
        _path_argument(command)
    agent_setup = agent_commands.add_parser("setup")
    agent_setup.add_argument("host", choices=("portable",))
    agent_setup.add_argument("--apply", action="store_true", help="Apply the shown adapter setup plan")
    _path_argument(agent_setup)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(getattr(args, "path", "."))
    if args.command == "init" and args.name:
        root /= args.name
    project = AnchorProject.at(root)

    try:
        if args.command in {"install", "uninstall"}:
            return _run_skill_install(args, root)
        if args.command in {"init", "add"}:
            preview = project.preview_setup(args.command)
            if not args.apply:
                print("\n".join(preview.lines()))
                return 0
            created = project.apply_setup(args.command)
            print(
                "Anchor is ready."
                if created
                else "Anchor was already configured; generated support files were checked."
            )
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0

        if args.command == "help":
            _print_help()
            return 0
        if args.command == "status":
            print(json.dumps(project.status(), indent=2))
            return 0
        if args.command == "doctor":
            _print_doctor(project)
            return 0
        if args.command == "start":
            task = project.start_task(args.title)
            print(f"Started {task['id']}: {task['title']} (briefing)")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command == "brief":
            task = project.record_brief(
                by=args.by,
                values={
                    "outcome": args.outcome,
                    "scope": args.scope,
                    "constraints": args.constraints,
                    "invariant": args.invariant,
                    "uncertainty": args.uncertainty,
                },
            )
            print(f"Engineer brief recorded for {task['id']}.")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command == "plan":
            task = project.plan_task(args.summary)
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command == "approve":
            provenance, interactive_confirmed = _approval_capture(args.provenance)
            task = project.approve_task(
                args.by,
                provenance=provenance,
                interactive_confirmed=interactive_confirmed,
            )
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command == "precommit":
            task = project.precommit()
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command == "verify":
            provenance, interactive_confirmed = _approval_capture(args.provenance)
            task = project.verify_task(
                by=args.by,
                result=args.result,
                reason=args.reason,
                provenance=provenance,
                interactive_confirmed=interactive_confirmed,
            )
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command == "revise":
            task = project.revise_task(target=args.target, reason=args.reason)
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command in TASK_TRANSITIONS:
            task = project.transition(args.command)
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command == "rules":
            return _run_rules(project, args)
        if args.command == "agent":
            return _run_agent(project, args)
    except AnchorError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 1


def _run_rules(project: AnchorProject, args: argparse.Namespace) -> int:
    if args.rule_command == "list":
        for rule in project.list_rules():
            print(f"{rule['id']}  {rule['category']}  {rule['status']}  [{rule['location']}]")
            print(f"  {rule['wording']}")
        return 0
    if args.rule_command == "propose":
        rule = project.propose_rule(args.category, args.wording)
        print(f"Proposed {rule['id']}. It is inactive until an engineer runs: anchor rules approve {rule['id']}")
        return 0
    if args.rule_command == "approve":
        provenance, interactive_confirmed = _approval_capture(args.provenance)
        rule = project.approve_rule(
            args.rule_id,
            by=args.by,
            provenance=provenance,
            interactive_confirmed=interactive_confirmed,
        )
        print(f"Approved {rule['id']} version {rule['version']}.")
        return 0
    if args.rule_command == "supersede":
        provenance, interactive_confirmed = _approval_capture(args.provenance)
        result = project.supersede_rule(
            old_rule_id=args.old_rule_id,
            new_rule_id=args.new_rule_id,
            by=args.by,
            reason=args.reason,
            provenance=provenance,
            interactive_confirmed=interactive_confirmed,
        )
        print(f"Active {result['category']} rule is now {result['active_rule']}.")
        return 0
    return 1


def _run_skill_install(args: argparse.Namespace, root: Path) -> int:
    installer = SkillInstaller(root)
    if args.command == "install":
        preview = installer.preview_install(platform=args.platform, project_scoped=args.project)
        if not args.apply:
            print("\n".join(preview.lines()))
            print(_skill_apply_instruction(args, root))
            return 0
        installation = installer.install(
            platform=args.platform,
            project_scoped=args.project,
            force=args.force,
        )
        print(
            f"Installed AnchorLoop {installation.platform} skill "
            f"({installation.version}) at {installation.destination}."
        )
        return 0

    preview = installer.preview_uninstall(platform=args.platform, project_scoped=args.project)
    if not args.apply:
        print("\n".join(preview.lines()))
        print(_skill_apply_instruction(args, root))
        return 0
    installation = installer.uninstall(
        platform=args.platform,
        project_scoped=args.project,
        force=args.force,
    )
    print(f"Removed AnchorLoop {installation.platform} skill from {installation.destination}.")
    return 0


def _approval_capture(provenance: str) -> tuple[str, bool]:
    if provenance == "audit":
        return provenance, False
    if provenance == "interactive-tty" and not sys.stdin.isatty():
        raise AnchorError(
            "interactive-tty provenance requires an interactive terminal. "
            "Use audit when recording an auditable but non-authenticated action."
        )
    try:
        confirmation = input("Type APPROVE to record an interactive approval: ").strip()
    except EOFError as error:
        raise AnchorError("Interactive approval confirmation was not received.") from error
    if confirmation != "APPROVE":
        raise AnchorError("Interactive approval was not confirmed.")
    return provenance, True


def _skill_apply_command(args: argparse.Namespace) -> str:
    parts = ["anchor", args.command]
    if args.project:
        parts.append("--project")
    parts.extend(["--platform", args.platform, "--apply"])
    if args.force:
        parts.append("--force")
    return " ".join(parts)


def _skill_apply_instruction(args: argparse.Namespace, root: Path) -> str:
    command = _skill_apply_command(args)
    if args.path == ".":
        return f"Apply with: {command}"
    return f"From {root.resolve()}, apply with: {command}"


def _run_agent(project: AnchorProject, args: argparse.Namespace) -> int:
    if args.agent_command == "detect":
        print(json.dumps(project.detect_agent_capabilities(), indent=2))
        return 0
    if args.agent_command == "status":
        print(json.dumps(project.agent_status(), indent=2))
        return 0
    if args.agent_command == "setup":
        if not args.apply:
            print("\n".join(project.preview_agent_setup(args.host)))
            return 0
        adapter = project.setup_agent(args.host)
        print(f"Configured agent-neutral {adapter['host']} adapter.")
        return 0
    return 1


def _print_help() -> None:
    print(
        "ANCHOR\n"
        "Engineer owns scope, decisions, rules, skills, and acceptance.\n"
        "The agent may write code only after an explicit approval.\n\n"
        "Setup:   anchor add --apply\n"
        "Skill:   anchor install --project --platform agents --apply\n"
        "Task:    anchor start \"short title\" -> brief -> plan -> approve -> implement -> review -> precommit -> verify -> close\n"
        "Rules:   anchor rules list | propose | approve | supersede\n"
        "Agent:   anchor agent detect | setup portable | status\n\n"
        "After anchor start, provide:\n"
        "Outcome:\nScope / non-goals:\nConstraints:\nInvariant or acceptance case:\nMain uncertainty:\n\n"
        "Record with: anchor brief --by <engineer> --outcome <text> --scope <text> --constraints <text> "
        "--invariant <text> --uncertainty <text>\n"
    )


def _print_doctor(project: AnchorProject) -> None:
    payload = project.doctor()
    payload["graphify"] = "not-installed (approval required)"
    payload["python"] = sys.version.split()[0]
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
