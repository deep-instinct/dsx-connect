from __future__ import annotations
from typing import Final


try:
    from dsx_connect.config import get_config
    ENV: Final = str(get_config().app_env.value) # "dev" | "stg" | "prod"
except Exception: # during unit tests, scripts, etc.
    ENV: Final = "dev"


try:
    from shared.routes import SERVICE_SLUG # e.g., "dsx-connect"
except Exception:
    SERVICE_SLUG = "dsx-connect"


NS: Final = f"{ENV}:{SERVICE_SLUG}" # global namespace prefix for Redis keys/channels