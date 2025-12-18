from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_DIR = Path.home() / ".dsxa"
CONFIG_PATH = CONFIG_DIR / "config.json"


def _empty_config() -> Dict[str, Any]:
    return {"current": None, "contexts": {}}


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return _empty_config()
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return _empty_config()
        data.setdefault("current", None)
        data.setdefault("contexts", {})
        return data
    except Exception:
        # fall back to empty if the file is malformed
        return _empty_config()


def save_config(config: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)


def get_context(config: Dict[str, Any], name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    return config.get("contexts", {}).get(name)


def set_context(config: Dict[str, Any], name: str, context: Dict[str, Any]) -> Dict[str, Any]:
    contexts = config.setdefault("contexts", {})
    contexts[name] = context
    return config


def set_current(config: Dict[str, Any], name: Optional[str]) -> Dict[str, Any]:
    config["current"] = name
    return config
