# Commit Agent

An autonomous AI-powered git commit agent that analyzes your staged and unstaged changes, groups them into logical commits, generates Conventional Commit messages, and walks you through an interactive approval flow before touching your repository.

Git operations only execute after you explicitly approve each commit.

## How it works

1. **Diff Analyzer** — reads all changed files and writes a technical summary of each one
2. **Commit Planner** — groups files into logical commits based on their summaries
3. **Message Writer** — generates a Conventional Commit message for each group
4. **Risk Reviewer** — flags potential issues (secrets, breaking changes, large deletions)
5. **Approval Flow** — shows each proposed commit; you approve, edit, skip, or quit

## Requirements

- Python 3.9+
- Git
- An `ANTHROPIC_API_KEY` environment variable

## Installation

```bash
pip install -e .
```

With dev dependencies for testing:

```bash
pip install -e ".[dev]"
```

> **Corporate proxy / SSL note:** If you're behind a corporate proxy that intercepts TLS, add
> `--trusted-host pypi.org --trusted-host files.pythonhosted.org` to the pip command.

## Quick start

```bash
export ANTHROPIC_API_KEY=sk-ant-...

cd /path/to/your/repo
# make some changes, then:
commit-agent
```

The agent scans your changes, calls Claude to plan the commits, and presents each one for review:

```
╭─────────────────────────────────────────────────────╮
│ Commit Agent  |  branch: main  |  2 proposed commits │
╰─────────────────────────────────────────────────────╯

┌ Commit 1/2  feat(auth): add JWT login endpoint ──────┐
│                                                       │
│ Files:                                                │
│   src/auth/login.py                                   │
│     Adds POST /login that issues signed JWT tokens    │
│   tests/test_login.py                                 │
│     Unit tests covering success and invalid-creds     │
└───────────────────────────────────────────────────────┘
  [a]pprove  [e]dit  [s]kip  [q]uit
```

## Usage

```bash
# Analyze all changes in the current directory
commit-agent

# Only consider already-staged changes
commit-agent --staged

# Dry run — show what would be committed without executing
commit-agent --dry-run

# Push after committing (overrides config)
commit-agent --push

# Suppress push even if auto_push is true in config
commit-agent --no-push

# Use a specific repository path
commit-agent --repo /path/to/repo

# Use a custom config file
commit-agent --config /path/to/config.yaml
```

## Approval flow controls

| Key | Action |
|-----|--------|
| `a` | Approve the commit as-is |
| `e` | Edit the commit message, then approve |
| `s` | Skip this commit (files remain uncommitted) |
| `q` | Quit — no further commits are processed |

## Configuration

Copy `config.example.yaml` to `config.yaml` in the repo root, or to `~/.commit-agent.yaml` for a user-wide default:

```yaml
anthropic:
  model: claude-opus-5
  max_tokens: 4096

git:
  protected_branches:
    - main
    - master
  auto_push: false   # set true to be prompted to push after every run

commit:
  conventional: true

ui:
  show_diff_in_preview: true
```

Config file search order:
1. `--config` flag
2. `./config.yaml`
3. `./.commit-agent.yaml`
4. `~/.commit-agent.yaml`
5. Built-in defaults

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key — get one at console.anthropic.com |

## Running tests

```bash
pytest
```
