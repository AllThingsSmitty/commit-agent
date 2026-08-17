import pytest
from pathlib import Path
import tempfile
import yaml

from commit_agent.config import Config


def test_load_defaults_when_no_file():
    config = Config.load(Path("/nonexistent/path/config.yaml"))
    assert config.anthropic.model == "claude-opus-5"
    assert config.anthropic.max_tokens == 4096
    assert config.git.protected_branches == ["main", "master"]
    assert config.git.auto_push is False
    assert config.commit.conventional is True
    assert config.ui.show_diff_in_preview is True


def test_load_from_file():
    data = {
        "anthropic": {"model": "claude-sonnet-5", "max_tokens": 2048},
        "git": {"protected_branches": ["main"], "auto_push": True},
        "commit": {"conventional": False},
        "ui": {"show_diff_in_preview": False},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        tmp_path = Path(f.name)

    try:
        config = Config.load(tmp_path)
        assert config.anthropic.model == "claude-sonnet-5"
        assert config.anthropic.max_tokens == 2048
        assert config.git.protected_branches == ["main"]
        assert config.git.auto_push is True
        assert config.commit.conventional is False
        assert config.ui.show_diff_in_preview is False
    finally:
        tmp_path.unlink()


def test_load_partial_config():
    data = {"anthropic": {"model": "claude-haiku-4-5"}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        tmp_path = Path(f.name)

    try:
        config = Config.load(tmp_path)
        assert config.anthropic.model == "claude-haiku-4-5"
        # Unspecified sections use defaults
        assert config.git.auto_push is False
        assert config.ui.show_diff_in_preview is True
    finally:
        tmp_path.unlink()


def test_load_empty_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("")
        tmp_path = Path(f.name)

    try:
        config = Config.load(tmp_path)
        assert config.anthropic.model == "claude-opus-5"
    finally:
        tmp_path.unlink()
