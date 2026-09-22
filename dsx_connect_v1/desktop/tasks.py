from __future__ import annotations

import json
import re
from pathlib import Path

from invoke import Exit, task

PROJECT_ROOT = Path(__file__).resolve().parent
PACKAGE_JSON = PROJECT_ROOT / "package.json"
PACKAGE_LOCK = PROJECT_ROOT / "package-lock.json"


def _is_semver(version: str) -> bool:
    return re.fullmatch(r"\d+\.\d+\.\d+", version) is not None


def _increment_patch(version: str) -> str:
    major, minor, patch = [int(part) for part in version.split(".")]
    return f"{major}.{minor}.{patch + 1}"


def _read_version(path: Path) -> str:
    return json.loads(path.read_text())["version"]


def _write_version(path: Path, version: str) -> None:
    data = json.loads(path.read_text())
    data["version"] = version
    if path.name == "package-lock.json" and isinstance(data.get("packages"), dict) and "" in data["packages"]:
        data["packages"][""]["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n")


@task(help={
    "version": "Explicit version to set (X.Y.Z). If omitted, bump the current patch version.",
})
def bump(c, version: str = ""):
    """
    Bump the DSX-Connect Desktop version across package files.

    Examples:
      inv bump
      inv bump --version 0.8.2
    """
    del c
    package_version = _read_version(PACKAGE_JSON)
    lock_version = _read_version(PACKAGE_LOCK)
    if package_version != lock_version:
        raise Exit(
            f"DSX-Connect Desktop version files are out of sync: "
            f"package.json={package_version}, package-lock.json={lock_version}. "
            f"Run `inv bump --version <x.y.z>` to repair them.",
            code=2,
        )

    target_version = version.strip() if version else _increment_patch(package_version)
    if not _is_semver(target_version):
        raise Exit(f"Invalid version '{target_version}'. Expected X.Y.Z.", code=2)

    if target_version == package_version:
        print(f"DSX-Connect Desktop already at {package_version}")
        return

    _write_version(PACKAGE_JSON, target_version)
    _write_version(PACKAGE_LOCK, target_version)
    print(f"DSX-Connect Desktop version bumped: {package_version} -> {target_version}")
