from pathlib import Path

from ..logging_config import get_logger

logger = get_logger("agents")


def load_prompt_template(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error(f"Prompt template not found: {path}")
        raise RuntimeError(f"Prompt template not found: {path}") from None
    except OSError as e:
        logger.error(f"Failed to read prompt template {path}: {e}")
        raise RuntimeError(f"Failed to read prompt template {path}: {e}") from e
