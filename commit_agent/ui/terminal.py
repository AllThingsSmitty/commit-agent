from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax
from rich import box
from rich.prompt import Prompt, Confirm

from ..models import CommitGroup, AnnotatedChange, RiskFlag, RiskSeverity, ApprovedCommit, CommitResult

console = Console()

_SEVERITY_COLORS = {
    RiskSeverity.low: "yellow",
    RiskSeverity.medium: "orange3",
    RiskSeverity.high: "red",
}

_COMMIT_TYPE_COLORS = {
    "feat": "green",
    "fix": "red",
    "docs": "blue",
    "style": "cyan",
    "refactor": "magenta",
    "perf": "yellow",
    "test": "cyan",
    "build": "orange3",
    "ci": "orange3",
    "chore": "dim white",
    "revert": "red",
}


def show_header(commit_count: int, flag_count: int, branch: str) -> None:
    flag_text = f"  [red]{flag_count} risk flag{'s' if flag_count != 1 else ''}[/red]" if flag_count else ""
    console.print()
    console.print(
        Panel(
            f"[bold]Commit Agent[/bold]  |  branch: [cyan]{branch}[/cyan]  |  "
            f"[green]{commit_count}[/green] proposed commit{'s' if commit_count != 1 else ''}{flag_text}",
            box=box.ROUNDED,
            border_style="dim",
        )
    )


def show_risk_flags(flags: list[RiskFlag]) -> bool:
    if not flags:
        return True

    console.print()
    console.print("[bold red]Risk Flags Detected[/bold red]")

    for flag in flags:
        color = _SEVERITY_COLORS[flag.severity]
        files_str = ", ".join(flag.affected_files) if flag.affected_files else "unknown"
        console.print(
            Panel(
                f"[{color}][bold]{flag.severity.value.upper()}[/bold][/{color}]  {flag.message}\n"
                f"[dim]Affected: {files_str}[/dim]",
                border_style=color,
                box=box.SIMPLE,
            )
        )

    console.print()
    return Confirm.ask("[yellow]Risk flags found. Continue anyway?[/yellow]", default=False)


def approval_flow(
    groups: list[CommitGroup],
    annotated_changes: list[AnnotatedChange],
    flags: list[RiskFlag],
    show_diff: bool = True,
) -> list[ApprovedCommit]:
    summary_map = {ac.file.path: ac.summary for ac in annotated_changes}
    approved: list[ApprovedCommit] = []

    for idx, group in enumerate(groups, start=1):
        console.print()
        _show_commit_card(idx, len(groups), group, summary_map, show_diff)

        while True:
            choice = Prompt.ask(
                "  [dim][a]pprove  [e]dit  [s]kip  [q]uit[/dim]",
                choices=["a", "e", "s", "q"],
                default="a",
            )

            if choice == "q":
                console.print("[dim]Quitting — no further commits will be processed.[/dim]")
                return approved

            if choice == "s":
                console.print(f"  [dim]Skipped commit {idx}.[/dim]")
                break

            if choice == "e":
                custom_msg = _edit_message(group)
                approved.append(ApprovedCommit(group=group, approved=True, custom_message=custom_msg))
                console.print(f"  [green]Edited and approved.[/green]")
                break

            if choice == "a":
                approved.append(ApprovedCommit(group=group, approved=True))
                console.print(f"  [green]Approved.[/green]")
                break

    return approved


def confirm_push(branch: str, is_protected: bool) -> bool:
    console.print()
    if is_protected:
        console.print(f"[yellow]Warning: [bold]{branch}[/bold] is a protected branch.[/yellow]")

    return Confirm.ask(
        f"Push commits to [cyan]{branch}[/cyan]?",
        default=not is_protected,
    )


def show_results(results: list[CommitResult], dry_run: bool = False) -> None:
    console.print()

    if dry_run:
        console.print("[bold yellow]Dry run — no commits were made.[/bold yellow]")
        return

    if not results:
        console.print("[dim]No commits were made.[/dim]")
        return

    table = Table(title="Commits Created", box=box.SIMPLE_HEAVY, show_header=True)
    table.add_column("Hash", style="cyan", no_wrap=True)
    table.add_column("Message")
    table.add_column("Files", justify="right")
    table.add_column("Pushed", justify="center")

    for result in results:
        pushed_mark = "[green]yes[/green]" if result.pushed else "[dim]no[/dim]"
        table.add_row(
            result.hash[:8],
            result.message.split("\n")[0],
            str(len(result.files)),
            pushed_mark,
        )

    console.print(table)


def _show_commit_card(
    idx: int,
    total: int,
    group: CommitGroup,
    summary_map: dict[str, str],
    show_diff: bool,
) -> None:
    type_color = _COMMIT_TYPE_COLORS.get(group.commit_type.value, "white")
    type_badge = f"[{type_color}][bold]{group.commit_type.value}[/bold][/{type_color}]"
    scope_text = f"([cyan]{group.scope}[/cyan])" if group.scope else ""
    breaking = " [red bold]BREAKING[/red bold]" if group.breaking_change else ""

    header = Text()
    header.append(f"Commit {idx}/{total}  ", style="dim")
    header.append(group.commit_type.value, style=f"bold {type_color}")
    if group.scope:
        header.append(f"({group.scope})", style="cyan")
    if group.breaking_change:
        header.append("!", style="bold red")
    header.append(f": {group.subject}")

    body_lines = []
    if group.body:
        body_lines.append("")
        body_lines.append(group.body)

    body_lines.append("")
    body_lines.append("[bold]Files:[/bold]")
    for f in group.files:
        summary = summary_map.get(f, "")
        body_lines.append(f"  [dim]{f}[/dim]")
        if summary:
            body_lines.append(f"    [italic dim]{summary}[/italic dim]")

    console.print(
        Panel(
            "\n".join(body_lines),
            title=header,
            border_style=type_color,
            box=box.ROUNDED,
        )
    )


def _edit_message(group: CommitGroup) -> str:
    current = group.format_message()
    console.print(f"\n[dim]Current message:[/dim]\n{current}\n")
    console.print("[dim]Enter new commit message (single line or multi-line; blank line + Enter to finish):[/dim]")

    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line and lines:
            break
        lines.append(line)

    new_message = "\n".join(lines).strip()
    return new_message if new_message else current
