from __future__ import annotations

import json
import re
from pathlib import Path

from invoke import Exit, task

PROJECT_ROOT = Path(__file__).resolve().parent
PACKAGE_JSON = PROJECT_ROOT / "package.json"
PACKAGE_LOCK = PROJECT_ROOT / "package-lock.json"
TAURI_CONF = PROJECT_ROOT / "src-tauri" / "tauri.conf.json"
CARGO_TOML = PROJECT_ROOT / "src-tauri" / "Cargo.toml"
CARGO_LOCK = PROJECT_ROOT / "src-tauri" / "Cargo.lock"


def _is_semver(version: str) -> bool:
    return re.fullmatch(r"\d+\.\d+\.\d+", version) is not None


def _increment_patch(version: str) -> str:
    major, minor, patch = [int(part) for part in version.split(".")]
    return f"{major}.{minor}.{patch + 1}"


def _read_json_version(path: Path) -> str:
    return json.loads(path.read_text())["version"]


def _write_json_version(path: Path, version: str) -> None:
    data = json.loads(path.read_text())
    data["version"] = version
    if path.name == "package-lock.json" and isinstance(data.get("packages"), dict) and "" in data["packages"]:
        data["packages"][""]["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n")


def _read_versions() -> dict[str, str]:
    tauri_version = json.loads(TAURI_CONF.read_text())["version"]
    package_version = _read_json_version(PACKAGE_JSON)
    lock_version = _read_json_version(PACKAGE_LOCK)

    cargo_toml = CARGO_TOML.read_text()
    cargo_match = re.search(r'(?m)^version = "(\d+\.\d+\.\d+)"$', cargo_toml)
    if not cargo_match:
        raise ValueError(f"Unable to find package version in {CARGO_TOML}")

    return {
        "tauri.conf.json": tauri_version,
        "package.json": package_version,
        "package-lock.json": lock_version,
        "Cargo.toml": cargo_match.group(1),
    }


def _write_version(version: str) -> None:
    _write_json_version(PACKAGE_JSON, version)
    _write_json_version(PACKAGE_LOCK, version)

    tauri_data = json.loads(TAURI_CONF.read_text())
    tauri_data["version"] = version
    TAURI_CONF.write_text(json.dumps(tauri_data, indent=2) + "\n")

    cargo_toml = CARGO_TOML.read_text()
    cargo_toml, replacements = re.subn(
        r'(?m)^version = "\d+\.\d+\.\d+"$',
        f'version = "{version}"',
        cargo_toml,
        count=1,
    )
    if replacements != 1:
        raise ValueError(f"Unable to update package version in {CARGO_TOML}")
    CARGO_TOML.write_text(cargo_toml)

    cargo_lock = CARGO_LOCK.read_text()
    cargo_lock, replacements = re.subn(
        r'(?ms)(\[\[package\]\]\nname = "dsxa_desktop"\nversion = ")\d+\.\d+\.\d+(")',
        rf"\g<1>{version}\2",
        cargo_lock,
        count=1,
    )
    if replacements == 1:
        CARGO_LOCK.write_text(cargo_lock)


@task(help={
    "version": "Explicit version to set (X.Y.Z). If omitted, bump the current patch version.",
})
def bump(c, version: str = ""):
    """
    Bump the DSXA Desktop version across all required files.

    Examples:
      inv bump
      inv bump --version 1.2.4
    """
    del c
    versions = _read_versions()
    primary_versions = {
        "tauri.conf.json": versions["tauri.conf.json"],
        "package.json": versions["package.json"],
        "Cargo.toml": versions["Cargo.toml"],
    }
    if len(set(primary_versions.values())) != 1:
        formatted = ", ".join(f"{name}={value}" for name, value in versions.items())
        raise Exit(
            f"DSXA Desktop primary version files are out of sync: {formatted}. "
            f"Run `inv bump --version <x.y.z>` to repair them.",
            code=2,
        )

    current_version = primary_versions["tauri.conf.json"]
    target_version = version.strip() if version else _increment_patch(current_version)
    if not _is_semver(target_version):
        raise Exit(f"Invalid version '{target_version}'. Expected X.Y.Z.", code=2)

    drifted = len(set(versions.values())) != 1
    if target_version == current_version and not drifted:
        print(f"DSXA Desktop already at {current_version}")
        return

    _write_version(target_version)
    if target_version == current_version:
        print(f"DSXA Desktop version files synchronized at {current_version}")
    else:
        print(f"DSXA Desktop version bumped: {current_version} -> {target_version}")
