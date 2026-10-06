from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import paths

_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|token|secret|password|authorization|cookie)\b\s*[=:]\s*\S+"
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if _SECRET_RE.search(message):
            record.msg = _SECRET_RE.sub(lambda m: f"{m.group(1)}=[redacted]", message)
            record.args = ()
        return True


def setup_logging(level: str = "INFO", console: bool = True) -> Path:
    paths.ensure_dirs()
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log_path = paths.log_dir() / "terminal.log"
    file_handler = RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RedactingFilter())
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream.addFilter(RedactingFilter())
        logger.addHandler(stream)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
    return log_path
