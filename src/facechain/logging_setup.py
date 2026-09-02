"""Logging configuration -- TASK.md 8 (readable output), Phase 10 (structured logging).

Every log line carries the current run id once one exists, so lines from concurrent or
successive runs can be told apart in a shared log. The run id is held in a
`contextvars.ContextVar` rather than threaded through every call signature: it is
ambient context, not a parameter any of these functions act on.
"""

from __future__ import annotations

import contextvars
import logging
import sys

_run_id: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")

NOISY_LIBRARIES = ("httpx", "httpcore", "urllib3", "web3", "PIL")


def set_run_id(run_id: str) -> None:
    _run_id.set(run_id)


def get_run_id() -> str:
    return _run_id.get()


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        return True


def configure(verbose: bool = False, quiet: bool = False) -> None:
    """Install a single stderr handler.

    Logs go to **stderr**, never stdout: stdout carries the report and the machine-
    readable command output, so a caller piping `facechain report` somewhere must not
    receive log lines mixed into it.
    """
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.addFilter(_RunIdFilter())
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s [%(run_id)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)

    # Third-party per-request chatter is useful when debugging a scrape, but it drowns
    # the pipeline's own narrative at the default level.
    for name in NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.WARNING)
