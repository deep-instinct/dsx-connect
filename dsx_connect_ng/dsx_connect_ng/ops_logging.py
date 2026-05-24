from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any


def configure_ops_logging(name: str = "dsx-connect-ng", env_var: str = "LOG_LEVEL") -> logging.Logger:
    level_name = os.getenv(env_var, "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
        logger.addHandler(handler)
    return logger


ops_logging = configure_ops_logging()


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        **fields,
    }
    logger.log(level, json.dumps(payload, default=_json_default, sort_keys=True))


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
