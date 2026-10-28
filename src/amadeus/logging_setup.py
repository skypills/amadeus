from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .storage import paths

LOGGER_NAME = "amadeus"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    logger.propagate = False
    try:
        paths.ensure_dirs()
        log_path = paths.state_dir() / "amadeus.log"
        handler: logging.Handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    return logger
