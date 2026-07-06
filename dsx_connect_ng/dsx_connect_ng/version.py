"""DSX-Connect v2 version metadata."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
import tomllib


def _local_pyproject_version() -> str:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)
    return str(data["project"]["version"])


def resolve_version() -> str:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if pyproject_path.exists():
        return _local_pyproject_version()
    try:
        return package_version("dsx-connect-ng")
    except PackageNotFoundError:
        return "0.0.0"


DSX_CONNECT_VERSION = resolve_version()
