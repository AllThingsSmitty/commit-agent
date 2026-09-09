import logging
import os
from pathlib import Path


def setup_logging() -> logging.Logger:
    """
    Configure logging for commit-agent.
    Logs to file only by default; set COMMIT_AGENT_DEBUG=1 to enable console debug output.
    Log file is written to ~/.commit-agent.log
    """
    log_level = logging.DEBUG if os.getenv("COMMIT_AGENT_DEBUG") else logging.INFO
    log_file = Path.home() / ".commit-agent.log"

    logger = logging.getLogger("commit_agent")
    logger.setLevel(logging.DEBUG)

    # Clear any existing handlers
    logger.handlers.clear()

    # File handler - always capture everything
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler - only if debug mode enabled
    if log_level == logging.DEBUG:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_formatter = logging.Formatter(
            "[%(levelname)s] %(name)s: %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module."""
    return logging.getLogger(f"commit_agent.{name}")
