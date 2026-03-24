import os
from pathlib import Path
from typing import Optional

_DEVEVN_LOGGED = False


def _default_external_env_path(default_path: Optional[Path]) -> Optional[Path]:
    """
    For a repo-local default like connectors/<slug>/.dev.env, prefer a local-state
    path under ~/.dsx-connect-local/<slug>/.env.local when it exists.
    """
    if not default_path:
        return None
    try:
        p = default_path.expanduser()
    except Exception:
        p = default_path

    if p.name != ".dev.env":
        return None

    slug = p.parent.name
    if not slug:
        return None

    local_dir = Path.home() / ".dsx-connect-local" / slug
    preferred = local_dir / ".env.local"
    fallback = local_dir / ".dev.env"
    if preferred.exists():
        return preferred
    if fallback.exists():
        return fallback
    return None


def load_devenv(default_path: Optional[Path] = None,
                env_var: str = "DSXCONNECTOR_ENV_FILE") -> None:
    """
    Lightweight loader for a development-only env file.

    - If env var `DSXCONNECTOR_ENV_FILE` is set, use that path.
    - Else, if `default_path` is provided and exists, use it.
    - Parses simple KEY=VALUE lines, ignores blanks/comments.
    - Populates os.environ ONLY for keys that are not already set.
    """
    path_str = os.getenv(env_var)
    if path_str:
        try:
            path = Path(path_str).expanduser()
        except Exception:
            path = Path(path_str)
    else:
        path = _default_external_env_path(default_path) or (default_path if default_path else None)
    if not path:
        return
    try:
        if not path.exists():
            return
        from shared.dsx_logging import dsx_logging
        import logging as _logging
        applied = 0
        for line in path.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "=" not in s:
                continue
            key, val = s.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and (key not in os.environ or os.environ.get(key, "") == ""):
                os.environ[key] = val
                applied += 1

        # Log once, at INFO, with summary including effective LOG_LEVEL if set
        # If LOG_LEVEL provided by .dev.env, update logger now (silent)
        eff_level = os.environ.get("LOG_LEVEL")
        if eff_level:
            try:
                dsx_logging.setLevel(getattr(_logging, eff_level.upper(), _logging.INFO))
            except Exception:
                pass

        global _DEVEVN_LOGGED
        if not _DEVEVN_LOGGED:
            suffix = f", LOG_LEVEL={eff_level}" if eff_level else ""
            dsx_logging.info(f"Loading dev env from {path} (applied {applied} keys{suffix})")
            _DEVEVN_LOGGED = True
    except Exception:
        # Silent failure: dev convenience only
        return
