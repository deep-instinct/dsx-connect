import os
from pathlib import Path
from typing import Optional

_DEVEVN_LOGGED = False


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
    path: Optional[Path] = Path(path_str) if path_str else (default_path if default_path else None)
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
            if key and key not in os.environ:
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
