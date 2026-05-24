from __future__ import annotations

import os
from typing import Any


_MASK_ENV_NAMES = {"stg", "stage", "staging", "prod", "production"}


def runtime_env() -> str:
    return (
        os.getenv("DSXCONNECTOR_APP_ENV")
        or os.getenv("DSXCONNECT_APP_ENV")
        or os.getenv("APP_ENV")
        or "dev"
    ).strip().lower()


def should_mask_identifiers(env: str | None = None) -> bool:
    value = (env or runtime_env()).strip().lower()
    return value in _MASK_ENV_NAMES


def mask_identifier(value: str | None, prefix: int = 5, suffix: int = 3) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 10:
        return f"{raw[:2]}...{raw[-1:]}" if len(raw) > 3 else "***"
    return f"{raw[:prefix]}...{raw[-suffix:]}"


def maybe_mask_identifier(value: str | None, env: str | None = None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return mask_identifier(raw) if should_mask_identifiers(env) else raw


def _is_identifier_key(key: str) -> bool:
    k = (key or "").strip().lower()
    if not k:
        return False
    if k in {
        "tenant_id",
        "client_id",
        "sp_tenant_id",
        "sp_client_id",
        "sf_client_id",
        "user_id",
        "appid",
        "app_id",
        "application_id",
    }:
        return True
    return k.endswith("_tenant_id") or k.endswith("_client_id")


def _sanitize(obj: Any, parent_key: str = "", env: str | None = None) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v, parent_key=str(k), env=env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v, parent_key=parent_key, env=env) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize(v, parent_key=parent_key, env=env) for v in obj)
    if _is_identifier_key(parent_key) and isinstance(obj, str):
        return maybe_mask_identifier(obj, env=env)
    return obj


def config_for_log(config: Any, env: str | None = None) -> Any:
    if not should_mask_identifiers(env):
        return config

    try:
        model_dump = getattr(config, "model_dump", None)
        if callable(model_dump):
            data = model_dump()
        elif isinstance(config, dict):
            data = config
        else:
            return config
        return _sanitize(data, env=env)
    except Exception:
        return config

