"""Pipeline logging configuration.

Always writes DEBUG-level logs to a file in the run directory.
The ``-v`` flag controls terminal verbosity (INFO when set, WARNING otherwise).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Track the file handler so we can close it later and avoid duplicates.
_file_handler: logging.FileHandler | None = None


def setup_pipeline_logging(
    *,
    log_dir: Path,
    verbose: bool = False,
) -> Path:
    """Configure logging for a pipeline run.

    Parameters
    ----------
    log_dir:
        Directory where ``pipeline.log`` will be written.  Created if missing.
    verbose:
        When *True*, also emit INFO-level logs to the terminal (stderr).

    Returns
    -------
    Path
        The absolute path to the log file.
    """
    global _file_handler  # noqa: PLW0603

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "pipeline.log"

    root = logging.getLogger("dd_agents")

    # Remove any previous file handler from an earlier run in the same process.
    if _file_handler is not None:
        root.removeHandler(_file_handler)
        _file_handler.close()

    # --- File handler: always DEBUG ---
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT))
    _file_handler = fh

    root.addHandler(fh)
    root.setLevel(logging.DEBUG)

    # --- Console handler ---
    if verbose:
        # Only add a stream handler if one isn't already present.
        has_stream = any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers
        )
        if not has_stream:
            sh = logging.StreamHandler()
            sh.setLevel(logging.DEBUG)
            sh.setFormatter(logging.Formatter("%(name)s: %(message)s"))
            root.addHandler(sh)

    # Quiet noisy third-party loggers regardless of verbosity.
    for noisy in ("claude_agent_sdk", "asyncio", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_path


def close_pipeline_logging() -> None:
    """Flush and close the file handler."""
    global _file_handler  # noqa: PLW0603
    if _file_handler is not None:
        _file_handler.close()
        logging.getLogger("dd_agents").removeHandler(_file_handler)
        _file_handler = None
