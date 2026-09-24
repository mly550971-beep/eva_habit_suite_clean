"""
audit_log.py
------------
A separate log, distinct from the normal application log, that only records
actions Eva actually executed (opened an app, sent a pre-filled message,
etc). Kept separate so the user can quickly review "what did Eva actually
do today" without wading through debug noise.
"""

import logging
from logging.handlers import RotatingFileHandler


def setup_audit_logger(config) -> logging.Logger:
    log_file = config.get("audit_log", "file", default="logs/audit.log")
    max_bytes = config.get("audit_log", "max_bytes", default=1_048_576)
    backup_count = config.get("audit_log", "backup_count", default=5)

    logger = logging.getLogger("eva.audit")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    try:
        handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    except Exception:
        logger.addHandler(logging.NullHandler())

    return logger
