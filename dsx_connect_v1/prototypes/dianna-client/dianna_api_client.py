#!/usr/bin/env python3
"""Compatibility shim for prototype imports.

Prefer importing from `dsx_connect_sdk` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK_SRC = ROOT / "dsx_connect_sdk"
if str(SDK_SRC) not in sys.path:
    sys.path.insert(0, str(SDK_SRC))

from dsx_connect_sdk import DiannaApiClient, DiannaApiError

__all__ = ["DiannaApiClient", "DiannaApiError"]
