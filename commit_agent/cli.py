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
from .logging_config import setup_logging, get_logger

logger = get_logger("cli")

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
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Claude model to use (overrides config)"
    ),
    max_tokens: Optional[int] = typer.Option(
        None, "--max-tokens", help="Max tokens per LLM response (overrides config)"
    ),
) -> None:
    """Analyze git changes and create logical commits with AI-generated messages."""
    setup_logging()
    try:
        logger.info("Starting commit-agent")
        _run(repo_path, config_path, staged_only, dry_run, push, model, max_tokens)
        logger.info("Commit-agent completed successfully")
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        ui.console.print("\n[dim]Interrupted.[/dim]")
        raise typer.Exit(0)
    except Exception as exc:
        logger.exception(f"Fatal error: {exc}")
        ui.console.print(f"\n[red]Error:[/red] {exc}")
        raise typer.Exit(1)


def _run(
    repo_path: Optional[Path],
    config_path: Optional[Path],
    staged_only: bool,
    dry_run: bool,
    push_override: Optional[bool],
    model_override: Optional[str] = None,
    max_tokens_override: Optional[int] = None,
) -> None:
    # Load config
    logger.debug("Loading configuration")
    config = Config.load(config_path)
    if model_override:
        logger.info(f"Overriding model: {model_override}")
        config.anthropic.model = model_override
    if max_tokens_override:
        logger.info(f"Overriding max_tokens: {max_tokens_override}")
        config.anthropic.max_tokens = max_tokens_override

    # Connect to repo
    try:
        logger.debug("Connecting to git repository")
        git_service = GitService(repo_path)
    except RuntimeError as exc:
        logger.error(f"Failed to initialize git service: {exc}")
        ui.console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    branch = git_service.current_branch
    is_protected = branch in config.git.protected_branches
    logger.info(f"Working on branch: {branch} (protected={is_protected})")

    if git_service.is_detached:
        logger.warning("HEAD is detached")
        ui.console.print("[yellow]Warning: HEAD is detached.[/yellow]")

    if git_service.has_conflicts():
        logger.error("Merge conflicts detected")
        ui.console.print("[red]Merge conflicts detected — resolve them before running commit-agent.[/red]")
        raise typer.Exit(1)

    # Gather changes
    logger.debug(f"Gathering changes (staged_only={staged_only})")
    ui.console.print(f"\n[dim]Scanning changes on branch [cyan]{branch}[/cyan]...[/dim]")
    changes = git_service.get_changes(staged_only=staged_only)

    if not changes:
        logger.info("No changes detected")
        ui.console.print("[dim]No changes detected. Nothing to commit.[/dim]")
        raise typer.Exit(0)

    logger.info(f"Found {len(changes)} changed file(s)")
    ui.console.print(f"[dim]Found {len(changes)} changed file{'s' if len(changes) != 1 else ''}.[/dim]")

    # Set up LLM
    logger.debug(f"Initializing LLM service with model={config.anthropic.model}")
    llm = LLMService(model=config.anthropic.model, max_tokens=config.anthropic.max_tokens)

    # Run agents
    logger.info("Running DiffAnalyzer agent")
    ui.console.print("[dim]Analyzing changes...[/dim]")
    annotated = DiffAnalyzer(llm).analyze(changes)
    logger.debug(f"DiffAnalyzer produced {len(annotated)} annotated changes")

    logger.info("Running CommitPlanner agent")
    ui.console.print("[dim]Planning commits...[/dim]")
    plan = CommitPlanner(llm).plan(annotated)

    if not plan:
        logger.info("CommitPlanner produced no groups")
        ui.console.print("[dim]No commit groups produced. Nothing to commit.[/dim]")
        raise typer.Exit(0)

    logger.debug(f"CommitPlanner produced {len(plan)} commit groups")

    logger.info("Running MessageWriter agent")
    ui.console.print("[dim]Writing commit messages...[/dim]")
    groups = MessageWriter(llm).write(plan, annotated)
    logger.debug(f"MessageWriter produced {len(groups)} commit messages")

    logger.info("Running RiskReviewer agent")
    ui.console.print("[dim]Reviewing for risks...[/dim]")
    flags = RiskReviewer(llm).review(changes)
    if flags:
        logger.warning(f"RiskReviewer found {len(flags)} flag(s)")

    # Show header
    ui.show_header(len(groups), len(flags), branch)

    # Handle risk flags
    if flags:
        logger.info(f"Showing {len(flags)} risk flag(s) to user")
        proceed = ui.show_risk_flags(flags)
        if not proceed:
            logger.info("User aborted due to risk flags")
            ui.console.print("[dim]Aborted by user.[/dim]")
            raise typer.Exit(0)

    # Approval flow
    logger.info("Starting user approval flow")
    approved_commits = ui.approval_flow(
        groups,
        annotated,
        flags,
        show_diff=config.ui.show_diff_in_preview,
    )

    if not approved_commits:
        logger.info("No commits approved by user")
        ui.console.print("\n[dim]No commits approved.[/dim]")
        raise typer.Exit(0)

    approved_count = sum(1 for ac in approved_commits if ac.approved)
    logger.info(f"User approved {approved_count}/{len(approved_commits)} commits")

    if dry_run:
        logger.info("Dry-run mode: skipping commit execution")
        ui.show_results([], dry_run=True)
        raise typer.Exit(0)

    # Execute commits
    logger.info("Executing approved commits")
    results: list[CommitResult] = []
    for idx, approved in enumerate(approved_commits, 1):
        if not approved.approved:
            logger.debug(f"Skipping unapproved commit {idx}")
            continue

        try:
            logger.info(f"Executing commit {idx}: {approved.group.subject}")
            commit_hash = git_service.commit_group(
                approved.group, approved.custom_message, conventional=config.commit.conventional
            )
            results.append(
                CommitResult(
                    hash=commit_hash,
                    message=approved.get_message(conventional=config.commit.conventional),
                    files=approved.group.files,
                    pushed=False,
                )
            )
        except Exception as exc:
            logger.error(f"Failed to commit {approved.group.subject!r}: {exc}", exc_info=True)
            ui.console.print(f"[red]Failed to commit {approved.group.subject!r}: {exc}[/red]")

    logger.info(f"Successfully created {len(results)} commit(s)")

    # Push
    should_push = push_override if push_override is not None else config.git.auto_push
    if should_push and results:
        logger.debug(f"Push enabled, confirming with user (protected={is_protected})")
        do_push = ui.confirm_push(branch, is_protected)
        if do_push:
            try:
                logger.info("Pushing commits")
                git_service.push()
                for result in results:
                    result.pushed = True
                logger.info("Successfully pushed commits")
            except Exception as exc:
                logger.error(f"Push failed: {exc}", exc_info=True)
                ui.console.print(f"[red]Push failed: {exc}[/red]")
    else:
        logger.debug(f"Push not enabled (should_push={should_push}, results={len(results)})")

    ui.show_results(results)
