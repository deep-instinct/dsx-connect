"""Helpers to load dsx_connect_sdk from editable-repo or installed package."""

from __future__ import annotations

from typing import Any, Tuple


def load_sdk() -> Tuple[Any, Any] | tuple[None, None]:
    """Return (DSXConnectClient class, core error class) or (None, None) if unavailable."""
    try:
        from dsx_connect_sdk.client import DSXConnectClient
        from dsx_connect_sdk.exceptions import DSXConnectCoreApiError
        return DSXConnectClient, DSXConnectCoreApiError
    except Exception:
        pass

    # Repo layout fallback: dsx_connect_sdk/dsx_connect_sdk
    try:
        from dsx_connect_sdk.dsx_connect_sdk.client import DSXConnectClient
        from dsx_connect_sdk.dsx_connect_sdk.exceptions import DSXConnectCoreApiError
        return DSXConnectClient, DSXConnectCoreApiError
    except Exception:
        return None, None
