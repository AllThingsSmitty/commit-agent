from enum import Enum
from typing import Optional
from pydantic import BaseModel


class FileStatus(str, Enum):
    added = "added"
    modified = "modified"
    deleted = "deleted"
    renamed = "renamed"
    untracked = "untracked"


class RiskSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class CommitType(str, Enum):
    feat = "feat"
    fix = "fix"
    docs = "docs"
    style = "style"
    refactor = "refactor"
    perf = "perf"
    test = "test"
    build = "build"
    ci = "ci"
    chore = "chore"
    revert = "revert"


class FileChange(BaseModel):
    path: str
    status: FileStatus
    diff: str
    is_staged: bool
    size_bytes: int = 0
    is_binary: bool = False


class AnnotatedChange(BaseModel):
    file: FileChange
    summary: str


class CommitGroup(BaseModel):
    files: list[str]
    commit_type: CommitType
    scope: Optional[str] = None
    subject: str
    body: Optional[str] = None
    breaking_change: bool = False

    def format_message(self, conventional: bool = True) -> str:
        if conventional:
            header = self.commit_type.value
            if self.scope:
                header += f"({self.scope})"
            if self.breaking_change:
                header += "!"
            header += f": {self.subject}"
        else:
            header = self.subject

        if self.body:
            return f"{header}\n\n{self.body}"
        return header


class RiskFlag(BaseModel):
    severity: RiskSeverity
    message: str
    affected_files: list[str]


class ApprovedCommit(BaseModel):
    group: CommitGroup
    approved: bool
    custom_message: Optional[str] = None

    def get_message(self, conventional: bool = True) -> str:
        if self.custom_message:
            return self.custom_message
        return self.group.format_message(conventional=conventional)


class CommitResult(BaseModel):
    hash: str
    message: str
    files: list[str]
    pushed: bool = False
