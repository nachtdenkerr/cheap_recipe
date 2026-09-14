import logging
import time
from contextlib import contextmanager

from rich.logging import RichHandler


def setup_logging(level="INFO"):
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, show_path=True)],
    )
    logging.getLogger("httpx").setLevel("WARNING")      # quiet the noisy ones
    logging.getLogger("sqlalchemy.engine").setLevel("WARNING")

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
