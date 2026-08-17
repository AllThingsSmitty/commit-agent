from pathlib import Path
from typing import Optional
import sys

import typer

from .config import Config
from .git_service import GitService
from .llm_service import LLMService
from .agents.diff_analyzer import DiffAnalyzer
from .agents.commit_planner import CommitPlanner
from .agents.message_writer import MessageWriter
from .agents.risk_reviewer import RiskReviewer
from .models import CommitResult
from .ui import terminal as ui

app = typer.Typer(
    name="commit-agent",
    help="Autonomous AI-powered git commit agent",
    add_completion=False,
)


@app.command()
def run(
    repo_path: Optional[Path] = typer.Option(
        None, "--repo", "-r", help="Path to git repository (default: current directory)"
    ),
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config YAML file"
    ),
    staged_only: bool = typer.Option(
        False, "--staged", "-s", help="Only consider already-staged changes"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be committed without making commits"
    ),
    push: Optional[bool] = typer.Option(
        None, "--push/--no-push", help="Push after committing (overrides config)"
    ),
) -> None:
    """Analyze git changes and create logical commits with AI-generated messages."""
    try:
        _run(repo_path, config_path, staged_only, dry_run, push)
    except KeyboardInterrupt:
        ui.console.print("\n[dim]Interrupted.[/dim]")
        raise typer.Exit(0)
    except Exception as exc:
        ui.console.print(f"\n[red]Error:[/red] {exc}")
        raise typer.Exit(1)


def _run(
    repo_path: Optional[Path],
    config_path: Optional[Path],
    staged_only: bool,
    dry_run: bool,
    push_override: Optional[bool],
) -> None:
    # Load config
    config = Config.load(config_path)

    # Connect to repo
    try:
        git_service = GitService(repo_path)
    except RuntimeError as exc:
        ui.console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    branch = git_service.current_branch
    is_protected = branch in config.git.protected_branches

    if git_service.is_detached:
        ui.console.print("[yellow]Warning: HEAD is detached.[/yellow]")

    if git_service.has_conflicts():
        ui.console.print("[red]Merge conflicts detected — resolve them before running commit-agent.[/red]")
        raise typer.Exit(1)

    # Gather changes
    ui.console.print(f"\n[dim]Scanning changes on branch [cyan]{branch}[/cyan]...[/dim]")
    changes = git_service.get_changes(staged_only=staged_only)

    if not changes:
        ui.console.print("[dim]No changes detected. Nothing to commit.[/dim]")
        raise typer.Exit(0)

    ui.console.print(f"[dim]Found {len(changes)} changed file{'s' if len(changes) != 1 else ''}.[/dim]")

    # Set up LLM
    llm = LLMService(model=config.anthropic.model, max_tokens=config.anthropic.max_tokens)

    # Run agents
    ui.console.print("[dim]Analyzing changes...[/dim]")
    annotated = DiffAnalyzer(llm).analyze(changes)

    ui.console.print("[dim]Planning commits...[/dim]")
    plan = CommitPlanner(llm).plan(annotated)

    if not plan:
        ui.console.print("[dim]No commit groups produced. Nothing to commit.[/dim]")
        raise typer.Exit(0)

    ui.console.print("[dim]Writing commit messages...[/dim]")
    groups = MessageWriter(llm).write(plan, annotated)

    ui.console.print("[dim]Reviewing for risks...[/dim]")
    flags = RiskReviewer(llm).review(changes)

    # Show header
    ui.show_header(len(groups), len(flags), branch)

    # Handle risk flags
    if flags:
        proceed = ui.show_risk_flags(flags)
        if not proceed:
            ui.console.print("[dim]Aborted by user.[/dim]")
            raise typer.Exit(0)

    # Approval flow
    approved_commits = ui.approval_flow(
        groups,
        annotated,
        flags,
        show_diff=config.ui.show_diff_in_preview,
    )

    if not approved_commits:
        ui.console.print("\n[dim]No commits approved.[/dim]")
        raise typer.Exit(0)

    if dry_run:
        ui.show_results([], dry_run=True)
        raise typer.Exit(0)

    # Execute commits
    results: list[CommitResult] = []
    for approved in approved_commits:
        if not approved.approved:
            continue

        try:
            commit_hash = git_service.commit_group(approved.group, approved.custom_message)
            results.append(
                CommitResult(
                    hash=commit_hash,
                    message=approved.get_message(),
                    files=approved.group.files,
                    pushed=False,
                )
            )
        except Exception as exc:
            ui.console.print(f"[red]Failed to commit {approved.group.subject!r}: {exc}[/red]")

    # Push
    should_push = push_override if push_override is not None else config.git.auto_push
    if should_push and results:
        do_push = ui.confirm_push(branch, is_protected)
        if do_push:
            try:
                git_service.push()
                for result in results:
                    result.pushed = True
            except Exception as exc:
                ui.console.print(f"[red]Push failed: {exc}[/red]")

    ui.show_results(results)
