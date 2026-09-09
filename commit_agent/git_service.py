from pathlib import Path
from typing import Optional
import git
from git import Repo, InvalidGitRepositoryError

from .models import FileChange, FileStatus, CommitGroup
from .logging_config import get_logger

logger = get_logger("git_service")

DIFF_TRUNCATE_CHARS = 3000


class GitService:
    def __init__(self, repo_path: Optional[Path] = None):
        search_path = str(repo_path) if repo_path else "."
        try:
            self.repo = Repo(search_path, search_parent_directories=True)
            logger.info(f"Initialized repo at {self.repo.working_dir}")
        except InvalidGitRepositoryError as e:
            logger.error(f"No git repository found at or above: {search_path}")
            raise RuntimeError(f"No git repository found at or above: {search_path}")

    @property
    def current_branch(self) -> str:
        if self.is_detached:
            return self.repo.head.commit.hexsha[:8]
        return self.repo.active_branch.name

    @property
    def is_detached(self) -> bool:
        return self.repo.head.is_detached

    def has_conflicts(self) -> bool:
        return bool(self.repo.index.unmerged_blobs())

    def get_changes(self, staged_only: bool = False) -> list[FileChange]:
        logger.debug(f"Getting changes with staged_only={staged_only}")
        changes: list[FileChange] = []

        # Staged changes (index vs HEAD)
        try:
            head_commit = self.repo.head.commit
        except ValueError:
            # Empty repo — no commits yet
            head_commit = None
            logger.debug("Empty repository - no HEAD commit yet")

        if head_commit is not None:
            staged_diffs = head_commit.diff(None, staged=True)
        else:
            staged_diffs = self.repo.index.diff(None)

        for diff in staged_diffs:
            fc = self._parse_diff(diff, is_staged=True)
            if fc:
                changes.append(fc)

        if not staged_only:
            # Unstaged changes (working tree vs index)
            for diff in self.repo.index.diff(None):
                fc = self._parse_diff(diff, is_staged=False)
                if fc:
                    # Skip if already captured as staged for the same path
                    existing_paths = {c.path for c in changes}
                    if fc.path not in existing_paths:
                        changes.append(fc)

            # Untracked files
            for untracked in self.repo.untracked_files:
                try:
                    content = (Path(self.repo.working_dir) / untracked).read_text(
                        encoding="utf-8", errors="replace"
                    )
                    diff_text = content[:DIFF_TRUNCATE_CHARS]
                    if len(content) > DIFF_TRUNCATE_CHARS:
                        diff_text += "\n... [truncated]"
                    size = (Path(self.repo.working_dir) / untracked).stat().st_size
                except Exception:
                    diff_text = "[unreadable]"
                    size = 0

                changes.append(
                    FileChange(
                        path=untracked,
                        status=FileStatus.untracked,
                        diff=diff_text,
                        is_staged=False,
                        size_bytes=size,
                        is_binary=False,
                    )
                )

        return changes

    def commit_group(self, group: CommitGroup, custom_message: Optional[str] = None, conventional: bool = True) -> str:
        message = custom_message if custom_message else group.format_message(conventional=conventional)
        logger.info(f"Committing {len(group.files)} file(s): {message[:60]}...")

        try:
            head_commit = self.repo.head.commit
        except ValueError:
            head_commit = None

        # Determine which files are currently staged
        if head_commit is not None:
            currently_staged = {d.b_path or d.a_path for d in head_commit.diff(None, staged=True)}
        else:
            currently_staged = set()

        group_files = set(group.files)

        # Only add files not already staged — avoids committing unstaged hunks for
        # files with partial staging (some hunks staged, others not).
        unstaged_in_group = [f for f in group.files if f not in currently_staged]
        if unstaged_in_group:
            logger.debug(f"Adding {len(unstaged_in_group)} unstaged file(s) to index")
            self.repo.index.add(unstaged_in_group)

        # Temporarily unstage files that belong to other groups so this commit
        # doesn't include them.
        other_staged = [f for f in currently_staged if f not in group_files]
        if other_staged and head_commit is not None:
            logger.debug(f"Temporarily unstaging {len(other_staged)} file(s) from other groups")
            self.repo.index.reset(head_commit, paths=other_staged)

        try:
            commit = self.repo.index.commit(message)
            logger.info(f"Commit created with hash {commit.hexsha}")
        except Exception as e:
            logger.error(f"Failed to commit: {e}")
            raise

        # Restore the temporarily unstaged files for subsequent groups.
        if other_staged:
            logger.debug(f"Restoring {len(other_staged)} staged file(s) for subsequent commits")
            self.repo.index.add(other_staged)

        return commit.hexsha

    def push(self, remote: str = "origin") -> None:
        try:
            logger.info(f"Pushing to {remote}")
            origin = self.repo.remote(remote)
            origin.push()
            logger.info(f"Successfully pushed to {remote}")
        except Exception as e:
            logger.error(f"Failed to push to {remote}: {e}")
            raise

    def _parse_diff(self, diff: git.Diff, is_staged: bool) -> Optional[FileChange]:
        # Determine path (handle renames)
        if diff.renamed_file:
            path = diff.b_path or diff.a_path
            status = FileStatus.renamed
        elif diff.new_file:
            path = diff.b_path
            status = FileStatus.added
        elif diff.deleted_file:
            path = diff.a_path
            status = FileStatus.deleted
        else:
            path = diff.b_path or diff.a_path
            status = FileStatus.modified

        if not path:
            logger.debug("Skipping diff with no path")
            return None

        is_binary = diff.diff is None or (
            isinstance(diff.diff, bytes) and b"\x00" in diff.diff[:512]
        )

        if is_binary:
            diff_text = "[binary file]"
            size = 0
        else:
            try:
                raw = diff.diff
                if isinstance(raw, bytes):
                    diff_text = raw.decode("utf-8", errors="replace")
                else:
                    diff_text = raw or ""

                if len(diff_text) > DIFF_TRUNCATE_CHARS:
                    diff_text = diff_text[:DIFF_TRUNCATE_CHARS] + "\n... [truncated]"

                # Try to get file size
                try:
                    full_path = Path(self.repo.working_dir) / path
                    size = full_path.stat().st_size if full_path.exists() else 0
                except Exception as e:
                    logger.debug(f"Failed to get file size for {path}: {e}")
                    size = 0
            except Exception as e:
                logger.warning(f"Error reading diff for {path}: {e}")
                diff_text = "[error reading diff]"
                size = 0

        return FileChange(
            path=path,
            status=status,
            diff=diff_text,
            is_staged=is_staged,
            size_bytes=size,
            is_binary=is_binary,
        )
