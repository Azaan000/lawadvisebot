"""
Centralized logging setup.

Replaces scattered print() calls with real logging: severity levels
(INFO / WARNING / ERROR / CRITICAL), timestamps, and persistence to a
rotating file — so events survive a server restart and terminal scrollback
loss, and so "something broke" is actually greppable/alertable instead of
living only in whoever's terminal happened to be open at the time.

Usage in any module:
    from utils.logger import get_logger
    log = get_logger(__name__)
    log.info("Webhook POST received")
    log.warning("WhatsApp token expired")
    log.error(f"save_message failed: {e}")
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

os.makedirs(LOG_DIR, exist_ok=True)

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_formatter = logging.Formatter(_FORMAT)

_configured = False


def _configure_root():
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)

    console = logging.StreamHandler()
    console.setFormatter(_formatter)
    root.addHandler(console)

    # 5MB per file, keep 5 rotations — bounded disk usage, no manual
    # log-rotation cron job needed.
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(_formatter)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(name)