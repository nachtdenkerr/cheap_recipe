"""Logging for the pipeline CLI and the API alike.

Two outputs: the terminal (rich, colour, short) and a log file (plain, with
date, level and logger, so it can be grepped and kept). The file is where
"what did the planner and the critic do on that request" is answered after the
fact — each agent step logs at INFO (agents/planner.py, critic.py, loop.py).

    LOG_LEVEL=DEBUG            more detail (per-batch LLM calls, token counts)
    LOG_FILE=path/to/file.log  somewhere else; LOG_FILE= (empty) for none

The file rotates at 5 MB and keeps 5 old ones, so it never grows unbounded.
"""

import logging
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

from cheaprecipe.config import log_file as configured_log_file
from cheaprecipe.config import log_level as configured_log_level

_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Libraries that are loud at INFO and say nothing about our own steps.
_QUIET = ("httpx", "httpcore", "openai", "sqlalchemy.engine", "urllib3", "multipart")


def setup_logging(level: str | None = None, log_file: Path | None | bool = True) -> Path | None:
    """Configure the root logger once; returns the log file in use, if any.

    `log_file=True` means the configured one (LOG_FILE, else logs/
    cheaprecipe.log); pass a path to override, or None/False for none.
    """
    level = level or configured_log_level()
    path = configured_log_file() if log_file is True else (log_file or None)

    handlers: list[logging.Handler] = [RichHandler(rich_tracebacks=True, show_path=True)]
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        handlers.append(file_handler)

    # force: replace whatever a library or an earlier call installed, so
    # calling this twice (the API's lifespan under --reload) never doubles lines.
    logging.basicConfig(
        level=level, format="%(message)s", datefmt="%H:%M:%S", handlers=handlers, force=True
    )
    for name in _QUIET:
        logging.getLogger(name).setLevel("WARNING")
    return path


@contextmanager
def stage(name, logger, **context):
    logger.info("▶ %s %s", name, context or "")
    t0 = time.perf_counter()
    try:
        yield
    except Exception:
        logger.exception("✗ %s failed after %.2fs", name, time.perf_counter() - t0)
        raise
    else:
        logger.info("✓ %s in %.2fs", name, time.perf_counter() - t0)
