from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel


class AnthropicConfig(BaseModel):
    model: str = "claude-opus-5"
    max_tokens: int = 4096


class GitConfig(BaseModel):
    protected_branches: list[str] = ["main", "master"]
    auto_push: bool = False


class CommitConfig(BaseModel):
    conventional: bool = True


class UIConfig(BaseModel):
    show_diff_in_preview: bool = True


class Config(BaseModel):
    anthropic: AnthropicConfig = AnthropicConfig()
    git: GitConfig = GitConfig()
    commit: CommitConfig = CommitConfig()
    ui: UIConfig = UIConfig()

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        if path is None:
            candidates = [
                Path.cwd() / "config.yaml",
                Path.cwd() / ".commit-agent.yaml",
                Path.home() / ".commit-agent.yaml",
            ]
            path = next((p for p in candidates if p.exists()), None)

        if path is None or not path.exists():
            return cls()

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)
