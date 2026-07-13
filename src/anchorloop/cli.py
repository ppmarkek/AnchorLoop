from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .project import AnchorError, AnchorProject, TASK_TRANSITIONS


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
    for name in ("help", "status", "doctor", "plan", "approve", "implement", "review", "precommit", "verify", "close"):
        command = commands.add_parser(name)
        _path_argument(command)
        workflow_commands[name] = command

    workflow_commands["plan"].add_argument("--summary", required=True, help="Concrete plan prepared for engineer approval")
    workflow_commands["approve"].add_argument("--by", required=True, help="Engineer approving the recorded plan")
    workflow_commands["verify"].add_argument("--by", required=True, help="Engineer who performed manual verification")
    workflow_commands["verify"].add_argument("--result", required=True, choices=("pass", "fail", "partial", "not-applicable"))
    workflow_commands["verify"].add_argument("--reason", required=True, help="Observed verification outcome or accepted limitation")

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
    _path_argument(rule_approve)

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
        if args.command in {"init", "add"}:
            preview = project.preview_setup(args.command)
            if not args.apply:
                print("\n".join(preview.lines()))
                return 0
            created = project.apply_setup(args.command)
            print("Anchor is ready." if created else "Anchor was already configured; no state was replaced.")
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
            task = project.approve_task(args.by)
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command == "precommit":
            task = project.precommit()
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action_path.read_text(encoding="utf-8").strip())
            return 0
        if args.command == "verify":
            task = project.verify_task(by=args.by, result=args.result, reason=args.reason)
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
        rule = project.approve_rule(args.rule_id)
        print(f"Approved {rule['id']} version {rule['version']}.")
        return 0
    return 1


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
        "Task:    anchor start \"short title\" -> brief -> plan -> approve -> implement -> review -> precommit -> verify -> close\n"
        "Rules:   anchor rules list | propose | approve\n"
        "Agent:   anchor agent detect | setup portable | status\n\n"
        "After anchor start, provide:\n"
        "Outcome:\nScope / non-goals:\nConstraints:\nInvariant or acceptance case:\nMain uncertainty:\n\n"
        "Record with: anchor brief --by <engineer> --outcome <text> --scope <text> --constraints <text> "
        "--invariant <text> --uncertainty <text>\n"
    )


def _print_doctor(project: AnchorProject) -> None:
    project.require_setup()
    payload = {
        "anchor_configured": project.config_path.exists(),
        "active_task": project.active_task_path.exists(),
        "graphify": "not-installed (approval required)",
        "python": sys.version.split()[0],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
