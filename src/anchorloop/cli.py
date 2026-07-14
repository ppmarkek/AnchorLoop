from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .command import command_prefix, display_command
from .project import AnchorError, AnchorProject, TASK_MODES, TASK_TRANSITIONS
from .skill_install import (
    DEFAULT_PROJECT_PLATFORM,
    SUPPORTED_PLATFORMS,
    SUPPORTED_SKILL_RUNTIMES,
    SkillInstaller,
    platform_label,
)
from .version import VERSION


def _path_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", default=".", help="Project root (default: current directory)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=command_prefix(),
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
    workflow_commands["plan"].add_argument(
        "--mode",
        choices=["AUTO", *sorted(TASK_MODES)],
        default="AUTO",
        help="AUTO applies the risk recommendation; lowering it requires an override reason",
    )
    workflow_commands["plan"].add_argument("--task-type", default="general")
    workflow_commands["plan"].add_argument("--approach")
    workflow_commands["plan"].add_argument("--alternative", dest="rejected_alternative")
    workflow_commands["plan"].add_argument("--risk", dest="primary_risk")
    workflow_commands["plan"].add_argument("--verification", dest="verification_strategy")
    workflow_commands["plan"].add_argument("--human-artifact")
    workflow_commands["plan"].add_argument("--comprehension")
    workflow_commands["plan"].add_argument("--rollback-mitigation")
    workflow_commands["plan"].add_argument("--mode-override-reason")
    workflow_commands["plan"].add_argument("--by", help="Engineer owning the plan and human artifact")
    workflow_commands["doctor"].add_argument(
        "--strict",
        action="store_true",
        help="Fail when required protocol, event-log, or next-action state is missing or corrupt",
    )
    workflow_commands["doctor"].add_argument(
        "--repair",
        action="store_true",
        help="Replay prepared transactions and repair a torn final event-log record under the project lock",
    )
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
        "--recall",
        help="Immediate engineer comprehension check; CAREFUL delayed recall is recorded later with the recall command",
    )
    workflow_commands["verify"].add_argument("--agent-turns", type=int)
    workflow_commands["verify"].add_argument("--input-tokens", type=int)
    workflow_commands["verify"].add_argument("--output-tokens", type=int)
    workflow_commands["verify"].add_argument("--active-minutes", type=float)
    workflow_commands["verify"].add_argument("--agent-provider")
    workflow_commands["verify"].add_argument("--agent-model")
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

    recall = commands.add_parser("recall", help="Record a due delayed-recall result for a closed CAREFUL task")
    recall.add_argument("--task", required=True, dest="task_id")
    recall.add_argument("--by", required=True)
    recall.add_argument("--response", required=True)
    recall.add_argument("--score", required=True, type=int, choices=range(0, 6))
    _path_argument(recall)

    outcome = commands.add_parser(
        "outcome",
        help="Record an engineer-reported post-completion outcome for a closed task",
    )
    outcome.add_argument("--task", required=True, dest="task_id")
    outcome.add_argument("--by", required=True)
    outcome.add_argument("--defects", required=True, type=int, dest="defects_found")
    outcome.add_argument("--rollback", required=True, choices=("yes", "no"))
    outcome.add_argument(
        "--corrective-refactor",
        required=True,
        choices=("yes", "no"),
    )
    outcome.add_argument("--notes", required=True)
    _path_argument(outcome)

    report = commands.add_parser(
        "report",
        help="Print local model-by-mode pilot data from closed tasks",
    )
    report.add_argument("--format", choices=("json", "csv"), default="json")
    _path_argument(report)

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
        scope = command.add_mutually_exclusive_group()
        scope.add_argument("--project", action="store_true", help="Use the current project's skill directory")
        scope.add_argument("--global", dest="global_install", action="store_true", help="Use your user-level skill directory")
        target = command.add_mutually_exclusive_group()
        target.add_argument("--platform", choices=SUPPORTED_PLATFORMS)
        target.add_argument("--all", dest="all_platforms", action="store_true", help="Target every supported user-global agent")
        mode = command.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help=f"Apply the shown {name} operation")
        mode.add_argument("--preview", action="store_true", help="Show the operation without writing files")
        command.add_argument(
            "--force",
            action="store_true",
            help=(
                "Allow overwriting or removing modified skill assets"
                if name == "install"
                else "Remove modified skill assets owned by the installer"
            ),
        )
        if name == "install":
            command.add_argument(
                "--interactive",
                action="store_true",
                help="Open the guided project/global installer (requires a terminal)",
            )
            command.add_argument(
                "--skill-runtime",
                choices=SUPPORTED_SKILL_RUNTIMES,
                default="anchor",
                help=argparse.SUPPRESS,
            )
            command.add_argument("--npx-package", help=argparse.SUPPRESS)
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
    bundled_version = os.environ.get("ANCHORLOOP_BUNDLED_VERSION")
    if bundled_version is not None and bundled_version != VERSION:
        print(
            f"Error: npm launcher version {bundled_version} does not match bundled Python version {VERSION}.",
            file=sys.stderr,
        )
        return 2
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
            print(project.next_action())
            return 0

        if args.command == "help":
            _print_help()
            return 0
        if args.command == "status":
            print(json.dumps(project.status(), indent=2))
            return 0
        if args.command == "doctor":
            payload = _print_doctor(project, strict=args.strict, repair=args.repair)
            if (args.strict or args.repair) and payload["status"] != "ok":
                return 2
            return 0
        if args.command == "start":
            task = project.start_task(args.title)
            print(f"Started {task['id']}: {task['title']} (briefing)")
            print(project.next_action())
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
            print(project.next_action())
            return 0
        if args.command == "plan":
            task = project.plan_task(
                args.summary,
                mode=args.mode,
                task_type=args.task_type,
                approach=args.approach,
                rejected_alternative=args.rejected_alternative,
                primary_risk=args.primary_risk,
                verification_strategy=args.verification_strategy,
                human_artifact=args.human_artifact,
                comprehension=args.comprehension,
                rollback_mitigation=args.rollback_mitigation,
                mode_override_reason=args.mode_override_reason,
                by=args.by,
            )
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action())
            return 0
        if args.command == "approve":
            approval_preview = project.task_approval_preview() if args.provenance == "interactive-tty" else None
            provenance, interactive_confirmed = _approval_capture(
                args.provenance,
                subject=approval_preview,
            )
            task = project.approve_task(
                args.by,
                provenance=provenance,
                interactive_confirmed=interactive_confirmed,
                expected_subject_digest=(
                    approval_preview["subject_digest"] if approval_preview is not None else None
                ),
            )
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action())
            return 0
        if args.command == "recall":
            task = project.record_delayed_recall(
                task_id=args.task_id,
                by=args.by,
                response=args.response,
                score=args.score,
            )
            print(f"Delayed recall recorded for {task['id']} with score {args.score}/5.")
            return 0
        if args.command == "outcome":
            task = project.record_post_completion_outcome(
                task_id=args.task_id,
                by=args.by,
                defects_found=args.defects_found,
                rollback=args.rollback == "yes",
                corrective_refactor=args.corrective_refactor == "yes",
                notes=args.notes,
            )
            print(f"Post-completion outcome recorded for {task['id']}.")
            return 0
        if args.command == "report":
            _print_experiment_report(project.experiment_report(), output_format=args.format)
            return 0
        if args.command == "precommit":
            task = project.precommit()
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action())
            return 0
        if args.command == "verify":
            verification_preview = (
                project.verification_preview(result=args.result, reason=args.reason, recall=args.recall)
                if args.provenance == "interactive-tty"
                else None
            )
            provenance, interactive_confirmed = _approval_capture(
                args.provenance,
                subject=verification_preview,
            )
            task = project.verify_task(
                by=args.by,
                result=args.result,
                reason=args.reason,
                provenance=provenance,
                interactive_confirmed=interactive_confirmed,
                recall=args.recall,
                agent_turns=args.agent_turns,
                input_tokens=args.input_tokens,
                output_tokens=args.output_tokens,
                active_minutes=args.active_minutes,
                agent_provider=args.agent_provider,
                agent_model=args.agent_model,
                expected_subject_digest=(
                    verification_preview["subject_digest"]
                    if verification_preview is not None
                    else None
                ),
            )
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action())
            return 0
        if args.command == "revise":
            task = project.revise_task(target=args.target, reason=args.reason)
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action())
            return 0
        if args.command in TASK_TRANSITIONS:
            task = project.transition(args.command)
            print(f"Task {task['id']} is now {task['state']}.")
            print(project.next_action())
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
        approval_command = display_command(
            f"rules approve {rule['id']} --by <engineer>"
        )
        print(
            f"Proposed {rule['id']}. It is inactive until an engineer runs: "
            f"{approval_command}"
        )
        return 0
    if args.rule_command == "approve":
        approval_preview = (
            project.rule_approval_preview(args.rule_id)
            if args.provenance == "interactive-tty"
            else None
        )
        provenance, interactive_confirmed = _approval_capture(
            args.provenance,
            subject=approval_preview,
        )
        rule = project.approve_rule(
            args.rule_id,
            by=args.by,
            provenance=provenance,
            interactive_confirmed=interactive_confirmed,
            expected_subject_digest=(
                approval_preview["subject_digest"] if approval_preview is not None else None
            ),
        )
        print(f"Approved {rule['id']} version {rule['version']}.")
        return 0
    if args.rule_command == "supersede":
        supersession_preview = (
            project.rule_supersession_preview(
                old_rule_id=args.old_rule_id,
                new_rule_id=args.new_rule_id,
                reason=args.reason,
            )
            if args.provenance == "interactive-tty"
            else None
        )
        provenance, interactive_confirmed = _approval_capture(
            args.provenance,
            subject=supersession_preview,
        )
        result = project.supersede_rule(
            old_rule_id=args.old_rule_id,
            new_rule_id=args.new_rule_id,
            by=args.by,
            reason=args.reason,
            provenance=provenance,
            interactive_confirmed=interactive_confirmed,
            expected_subject_digest=(
                supersession_preview["subject_digest"]
                if supersession_preview is not None
                else None
            ),
        )
        print(f"Active {result['category']} rule is now {result['active_rule']}.")
        return 0
    return 1


_GLOBAL_INSTALL_MENU_PLATFORMS = ("codex", "cursor", "gemini", "claude", "opencode")
_INTERACTIVE_GLOBAL_PLATFORMS = (*_GLOBAL_INSTALL_MENU_PLATFORMS, "agents")


@dataclass(frozen=True)
class _SkillInstallSelection:
    project_scoped: bool
    platforms: tuple[str, ...]
    apply: bool


def _run_skill_install(args: argparse.Namespace, root: Path) -> int:
    installer = SkillInstaller(root)
    if args.command == "install":
        if _should_open_skill_installer(args):
            selection = _interactive_skill_install_selection(args, installer)
            if selection is None:
                return 0
            previews = _install_previews(
                installer,
                platforms=selection.platforms,
                project_scoped=selection.project_scoped,
                runtime=args.skill_runtime,
                npx_package=args.npx_package,
            )
            _print_skill_previews(previews)
            if not selection.apply:
                print("\nPreview only. Nothing was written.")
                return 0
            return _apply_skill_installations(
                installer,
                platforms=selection.platforms,
                project_scoped=selection.project_scoped,
                runtime=args.skill_runtime,
                npx_package=args.npx_package,
                force=args.force,
            )

        project_scoped = args.project
        platforms = _skill_platforms(args)
        previews = _install_previews(
            installer,
            platforms=platforms,
            project_scoped=project_scoped,
            runtime=args.skill_runtime,
            npx_package=args.npx_package,
        )
        _print_skill_previews(previews)
        if not args.apply:
            print(_skill_apply_instruction(args, root))
            return 0
        return _apply_skill_installations(
            installer,
            platforms=platforms,
            project_scoped=project_scoped,
            runtime=args.skill_runtime,
            npx_package=args.npx_package,
            force=args.force,
        )

    project_scoped = args.project
    platforms = _skill_platforms(args)
    previews = [
        installer.preview_uninstall(platform=platform, project_scoped=project_scoped)
        for platform in platforms
    ]
    _print_skill_previews(previews)
    if not args.apply:
        print(_skill_apply_instruction(args, root))
        return 0
    return _apply_skill_uninstallations(
        installer,
        platforms=platforms,
        project_scoped=project_scoped,
        force=args.force,
    )


def _skill_platforms(args: argparse.Namespace) -> tuple[str, ...]:
    if args.all_platforms:
        if args.project:
            raise AnchorError("--all is available only for a user-global installation; omit --project or use --global.")
        return _GLOBAL_INSTALL_MENU_PLATFORMS
    return (args.platform or DEFAULT_PROJECT_PLATFORM,)


def _should_open_skill_installer(args: argparse.Namespace) -> bool:
    if args.interactive:
        if args.platform or args.all_platforms:
            raise AnchorError("--interactive chooses agent destinations; do not combine it with --platform or --all.")
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise AnchorError("The guided installer requires an interactive terminal. Use --project/--global and --platform instead.")
        return True
    return (
        sys.stdin.isatty()
        and sys.stdout.isatty()
        and not args.apply
        and not args.preview
        and not args.platform
        and not args.all_platforms
    )


def _interactive_skill_install_selection(
    args: argparse.Namespace,
    installer: SkillInstaller,
) -> _SkillInstallSelection | None:
    _print_skill_installer_banner()
    project_scoped = _interactive_install_scope(args)
    if project_scoped is None:
        print("Setup cancelled. Nothing was written.")
        return None

    if project_scoped:
        platforms = (DEFAULT_PROJECT_PLATFORM,)
        print(
            "\nProject installs use the shared Agent Skills standard so compatible agents can discover "
            "the same project workflow."
        )
    else:
        platforms = _interactive_global_platforms(installer)
        if platforms is None:
            print("Setup cancelled. Nothing was written.")
            return None

    print("\nYour installation plan:")
    for platform in platforms:
        destination = installer.destination_for(platform=platform, project_scoped=project_scoped)
        print(f"  {_skill_symbol('•', '-')} {platform_label(platform):<22} {destination}")
    print("\nOnly AnchorLoop-owned skill files will be written. No project state, source code, or cache is created.")

    if args.preview:
        return _SkillInstallSelection(project_scoped=project_scoped, platforms=platforms, apply=False)
    if not _confirm_skill_installation():
        print("Setup cancelled. Nothing was written.")
        return None
    return _SkillInstallSelection(project_scoped=project_scoped, platforms=platforms, apply=True)


def _interactive_install_scope(args: argparse.Namespace) -> bool | None:
    if args.project:
        return True
    if args.global_install:
        return False
    print("\nWhere should AnchorLoop live?")
    print("  [1] This project   — shared with agents working in this repository")
    print("  [2] My profile     — available in every project for selected agents")
    print("  [Q] Cancel")
    choice = _read_skill_choice("Choose 1, 2, or Q", {"1", "2", "q"})
    if choice == "q":
        return None
    return choice == "1"


def _interactive_global_platforms(installer: SkillInstaller) -> tuple[str, ...] | None:
    print("\nWhich agents should receive AnchorLoop?")
    print("  [1] All native agent locations")
    for number, platform in enumerate(_INTERACTIVE_GLOBAL_PLATFORMS, start=2):
        destination = installer.destination_for(platform=platform, project_scoped=False)
        print(f"  [{number}] {platform_label(platform):<22} {destination}")
    print("  [Q] Cancel")
    choices = {"1", "q"} | {str(number) for number in range(2, len(_INTERACTIVE_GLOBAL_PLATFORMS) + 2)}
    choice = _read_skill_choice("Choose an agent", choices)
    if choice == "q":
        return None
    if choice == "1":
        return _GLOBAL_INSTALL_MENU_PLATFORMS
    return (_INTERACTIVE_GLOBAL_PLATFORMS[int(choice) - 2],)


def _print_skill_installer_banner() -> None:
    if not _skill_unicode_supported():
        print(_skill_ui_style("+--------------------------------------------------------------+", "36"))
        print(_skill_ui_style("|  ANCHORLOOP / SKILL SETUP                                   |", "1;36"))
        print(_skill_ui_style("|  One workflow. Any agent. Your state stays local.           |", "2"))
        print(_skill_ui_style("+--------------------------------------------------------------+", "36"))
        return
    border = "╭──────────────────────────────────────────────────────────────╮"
    print(_skill_ui_style(border, "36"))
    print(_skill_ui_style("│  ⚓  ANCHORLOOP / SKILL SETUP                                 │", "1;36"))
    print(_skill_ui_style("│      One workflow. Any agent. Your state stays local.        │", "2"))
    print(_skill_ui_style("╰──────────────────────────────────────────────────────────────╯", "36"))


def _skill_ui_style(value: str, code: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR") is not None:
        return value
    return f"\033[{code}m{value}\033[0m"


def _skill_unicode_supported() -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "⚓╭╰│✓×•→›".encode(encoding)
    except UnicodeEncodeError:
        return False
    return True


def _skill_symbol(unicode_value: str, ascii_value: str) -> str:
    return unicode_value if _skill_unicode_supported() else ascii_value


def _read_skill_choice(prompt: str, allowed: set[str]) -> str:
    while True:
        try:
            response = input(
                _skill_ui_style(f"\n{_skill_symbol('›', '>')} {prompt}: ", "1;36")
            ).strip().lower()
        except EOFError as error:
            raise AnchorError("Interactive setup input was not received.") from error
        if response in allowed:
            return response
        expected = ", ".join(sorted(choice.upper() if choice == "q" else choice for choice in allowed))
        print(f"Please choose one of: {expected}.")


def _confirm_skill_installation() -> bool:
    choice = _read_skill_choice("Install now? [Y/n]", {"", "y", "yes", "n", "no"})
    return choice in {"", "y", "yes"}


def _install_previews(
    installer: SkillInstaller,
    *,
    platforms: tuple[str, ...],
    project_scoped: bool,
    runtime: str,
    npx_package: str | None,
) -> list[object]:
    return [
        installer.preview_install(
            platform=platform,
            project_scoped=project_scoped,
            runtime=runtime,
            npx_package=npx_package,
        )
        for platform in platforms
    ]


def _print_skill_previews(previews: Sequence[object]) -> None:
    for index, preview in enumerate(previews, start=1):
        if index > 1:
            print()
        if len(previews) > 1:
            print(f"[{index}/{len(previews)}]")
        print("\n".join(preview.lines()))


def _apply_skill_installations(
    installer: SkillInstaller,
    *,
    platforms: tuple[str, ...],
    project_scoped: bool,
    runtime: str,
    npx_package: str | None,
    force: bool,
) -> int:
    installations = []
    failures: list[tuple[str, AnchorError]] = []
    for platform in platforms:
        try:
            installations.append(
                installer.install(
                    platform=platform,
                    project_scoped=project_scoped,
                    runtime=runtime,
                    npx_package=npx_package,
                    force=force,
                )
            )
        except AnchorError as error:
            failures.append((platform, error))

    _print_skill_install_results(installations, failures)
    return 2 if failures else 0


def _apply_skill_uninstallations(
    installer: SkillInstaller,
    *,
    platforms: tuple[str, ...],
    project_scoped: bool,
    force: bool,
) -> int:
    installations = []
    failures: list[tuple[str, AnchorError]] = []
    for platform in platforms:
        try:
            installations.append(
                installer.uninstall(platform=platform, project_scoped=project_scoped, force=force)
            )
        except AnchorError as error:
            failures.append((platform, error))

    _print_skill_uninstall_results(installations, failures)
    return 2 if failures else 0


def _print_skill_install_results(installations: Sequence[object], failures: Sequence[tuple[str, AnchorError]]) -> None:
    if len(installations) == 1 and not failures:
        installation = installations[0]
        print(
            f"Installed AnchorLoop {installation.platform} skill "
            f"({installation.version}) at {installation.destination}."
        )
        return
    for installation in installations:
        print(
            f"{_skill_symbol('✓', 'OK')} {platform_label(installation.platform)} "
            f"{_skill_symbol('→', '->')} {installation.destination}"
        )
    for platform, error in failures:
        print(
            f"{_skill_symbol('×', 'X')} {platform_label(platform)} "
            f"{_skill_symbol('→', '->')} {error}",
            file=sys.stderr,
        )
    if failures:
        if installations:
            print("Some destinations were installed; successful destinations were not rolled back.", file=sys.stderr)
        return
    print(f"AnchorLoop is ready for {len(installations)} agents.")


def _print_skill_uninstall_results(installations: Sequence[object], failures: Sequence[tuple[str, AnchorError]]) -> None:
    if len(installations) == 1 and not failures:
        installation = installations[0]
        print(f"Removed AnchorLoop {installation.platform} skill from {installation.destination}.")
        return
    for installation in installations:
        print(
            f"{_skill_symbol('✓', 'OK')} Removed {platform_label(installation.platform)} "
            f"from {installation.destination}"
        )
    for platform, error in failures:
        print(
            f"{_skill_symbol('×', 'X')} {platform_label(platform)} "
            f"{_skill_symbol('→', '->')} {error}",
            file=sys.stderr,
        )
    if failures and installations:
        print("Successful removals were not rolled back.", file=sys.stderr)


def _approval_capture(
    provenance: str,
    *,
    subject: dict[str, object] | None = None,
) -> tuple[str, bool]:
    if provenance == "audit":
        return provenance, False
    if provenance == "interactive-tty" and not sys.stdin.isatty():
        raise AnchorError(
            "interactive-tty provenance requires an interactive terminal. "
            "Use audit when recording an auditable but non-authenticated action."
        )
    if not subject or not isinstance(subject.get("subject_digest"), str):
        raise AnchorError("Interactive approval requires an exact subject digest.")
    digest = str(subject["subject_digest"])
    short_digest = digest.removeprefix("sha256:")[:12]
    print("Interactive approval subject:")
    print(json.dumps(subject, indent=2, sort_keys=True))
    expected = f"APPROVE {short_digest}"
    try:
        confirmation = input(f"Type {expected} to record this exact approval: ").strip()
    except EOFError as error:
        raise AnchorError("Interactive approval confirmation was not received.") from error
    if confirmation != expected:
        raise AnchorError("Interactive approval was not confirmed.")
    return provenance, True


def _skill_apply_command(args: argparse.Namespace) -> str:
    parts = [args.command]
    if args.project:
        parts.append("--project")
    elif args.global_install:
        parts.append("--global")
    if args.all_platforms:
        parts.append("--all")
    else:
        parts.extend(["--platform", args.platform or DEFAULT_PROJECT_PLATFORM])
    parts.append("--apply")
    if (
        args.command == "install"
        and args.skill_runtime != "anchor"
        and not command_prefix().startswith("npx --yes ")
    ):
        parts.extend(["--skill-runtime", args.skill_runtime, "--npx-package", args.npx_package])
    if args.force:
        parts.append("--force")
    return display_command(" ".join(parts))


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
    command = command_prefix()
    print(
        "ANCHOR\n"
        "Engineer owns scope, decisions, rules, skills, and acceptance.\n"
        "The agent may write code only after an explicit approval.\n\n"
        f"Setup:   {command} add --apply\n"
        f"Skill:   {command} install --interactive\n"
        f"Task:    {command} start \"short title\" -> brief -> plan -> approve -> implement -> review -> precommit -> verify -> close\n"
        f"Recall:  {command} recall --task <closed-task-id> --by <engineer> --response <text> --score 0..5\n"
        f"Outcome: {command} outcome --task <closed-task-id> --by <engineer> --defects <n> --rollback yes|no --corrective-refactor yes|no --notes <text>\n"
        f"Report:  {command} report --format json|csv\n"
        f"Rules:   {command} rules list | propose | approve | supersede\n"
        f"Agent:   {command} agent detect | setup portable | status\n\n"
        f"After {command} start, provide:\n"
        "Outcome:\nScope / non-goals:\nConstraints:\nInvariant or acceptance case:\nMain uncertainty:\n\n"
        f"Record with: {command} brief --by <engineer> --outcome <text> --scope <text> --constraints <text> "
        "--invariant <text> --uncertainty <text>\n"
    )


def _print_doctor(
    project: AnchorProject,
    *,
    strict: bool = False,
    repair: bool = False,
) -> dict[str, object]:
    payload = project.doctor(strict=strict, repair=repair)
    payload["graphify"] = "not-installed (approval required)"
    payload["python"] = sys.version.split()[0]
    print(json.dumps(payload, indent=2))
    return payload


def _print_experiment_report(
    payload: dict[str, object],
    *,
    output_format: str,
) -> None:
    if output_format == "json":
        print(json.dumps(payload, indent=2))
        return
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise AnchorError("Experiment report does not contain task rows.")
    fieldnames = [
        "task_id",
        "title",
        "mode",
        "task_type",
        "verification_result",
        "wall_seconds",
        "active_minutes",
        "agent_turns",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "agent_provider",
        "agent_model",
        "delayed_recall_score",
        "outcome_observations",
        "defects_found",
        "rollback",
        "corrective_refactor",
        "outcome_recorded_at",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in tasks:
        if not isinstance(row, dict):
            raise AnchorError("Experiment report task row is invalid.")
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
