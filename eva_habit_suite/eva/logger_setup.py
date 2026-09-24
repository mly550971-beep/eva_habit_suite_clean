"""
logger_setup.py
----------------
Sets up a unified logging system for the whole project: console output +
a rotating log file (so the file never grows unbounded).
"""

import logging
from logging.handlers import RotatingFileHandler


def setup_logger(config) -> logging.Logger:
    log_file = config.get("logging", "file", default="logs/jarvis.log")
    level_name = config.get("logging", "level", default="INFO")
    max_bytes = config.get("logging", "max_bytes", default=1_048_576)
    backup_count = config.get("logging", "backup_count", default=3)

    level = getattr(logging, str(level_name).upper(), logging.INFO)

    logger = logging.getLogger("jarvis")
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger  # avoid duplicate handlers if called more than once

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not create log file ({log_file}): {e}")

    return logger
