"""Structured JSON logging.

Every log record is one JSON object per line. Extra fields are passed with
``log.info("msg", extra={"fields": {...}})`` or the :func:`event` helper.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format a LogRecord as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    """Send JSON logs to stderr and, optionally, append them to ``log_file``."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(JsonFormatter())
        root.addHandler(h)
    # httpx logs every full URL (hundreds of coordinates); our own fetch events carry what matters
    logging.getLogger("httpx").setLevel(logging.WARNING)


def event(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    """Log ``msg`` with structured ``fields``."""
    logger.log(level, msg, extra={"fields": fields})
