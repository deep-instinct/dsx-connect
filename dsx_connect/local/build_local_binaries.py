#!/usr/bin/env python3
"""Build native binaries/app bundles for DSX-Connect local runtime CLIs via Nuitka."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import typer


app = typer.Typer(help="Build local runtime binaries (macOS-first MVP)")


@dataclass(frozen=True)
class BuildTarget:
    name: str
    source: Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _targets(repo: Path) -> dict[str, BuildTarget]:
    return {
        "core": BuildTarget(
            name="core",
            source=repo / "dsx_connect" / "local" / "dsx_connect_local.py",
        ),
        "filesystem": BuildTarget(
            name="filesystem",
            source=repo / "connectors" / "filesystem" / "local" / "filesystem_local.py",
        ),
        "core-gui": BuildTarget(
            name="core-gui",
            source=repo / "dsx_connect" / "local" / "dsx_connect_local_gui.py",
        ),
        "filesystem-gui": BuildTarget(
            name="filesystem-gui",
            source=repo / "connectors" / "filesystem" / "local" / "filesystem_local_gui.py",
        ),
    }


def _nuitka_module_available() -> bool:
    try:
        import nuitka  # noqa: F401
    except Exception:
        return False
    return True


def _build_selected_targets(target: str) -> list[BuildTarget]:
    targets = _targets(_repo_root())
    if target not in {"core", "filesystem", "core-gui", "filesystem-gui", "all"}:
        raise typer.BadParameter("target must be one of: core, filesystem, core-gui, filesystem-gui, all")
    return list(targets.values()) if target == "all" else [targets[target]]


def _default_app_icon_path(repo: Path) -> Path:
    return repo / "dsx_connect" / "app" / "static" / "images" / "dsx-connect-icon-outline.svg"


def _imageio_available() -> bool:
    try:
        import imageio  # noqa: F401
    except Exception:
        return False
    return True


def _convert_svg_to_png(svg_path: Path, output_dir: Path, name: str) -> Path | None:
    if shutil.which("rsvg-convert") is None:
        print("rsvg-convert not found; cannot convert SVG icon")
        return None

    icon_dir = output_dir / ".icons"
    icon_dir.mkdir(parents=True, exist_ok=True)
    out_png = icon_dir / f"{name}.png"
    try:
        subprocess.run(
            [
                "rsvg-convert",
                "-w",
                "1024",
                "-h",
                "1024",
                str(svg_path),
                "-o",
                str(out_png),
            ],
            check=True,
        )
    except subprocess.CalledProcessError:
        print("failed to convert SVG icon with rsvg-convert")
        return None
    return out_png


def _default_redis_binary_path() -> Path | None:
    candidates = [
        Path("/opt/homebrew/bin/redis-server"),
        Path("/usr/local/bin/redis-server"),
        Path("/usr/bin/redis-server"),
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def _resolve_redis_binary(redis_binary: str | None) -> Path | None:
    if redis_binary:
        p = Path(redis_binary).expanduser().resolve()
        if not p.exists() or not p.is_file():
            raise typer.BadParameter(f"redis binary not found: {p}")
        return p
    return _default_redis_binary_path()


def _resolve_app_icon(app_icon: str | None, target: BuildTarget, output_dir: Path) -> str | None:
    repo = _repo_root()
    icon_input = Path(app_icon).expanduser() if app_icon else _default_app_icon_path(repo)
    if not icon_input.exists():
        return None

    if not _imageio_available():
        print("imageio not installed; app icon disabled (install imageio for icon conversion)")
        return None

    # Nuitka/imageio cannot ingest SVG directly in this path, so convert first.
    if icon_input.suffix.lower() == ".svg":
        png = _convert_svg_to_png(icon_input, output_dir, f"{target.source.stem}-icon")
        if png is None:
            return None
        return str(png)

    return str(icon_input)


def _run_build(
    *,
    target: BuildTarget,
    output_dir: Path,
    onefile: bool,
    macos_sign_identity: str | None,
    app_bundle: bool,
    app_name_prefix: str,
    app_icon: str | None,
    redis_binary: Path | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--follow-imports",
        f"--output-dir={output_dir}",
        f"--output-filename={target.source.stem}",
        "--remove-output",
    ]

    if app_bundle:
        cmd.append("--macos-create-app-bundle")
        cmd.append(f"--macos-app-name={app_name_prefix}-{target.source.stem}")
        resolved_icon = _resolve_app_icon(app_icon, target, output_dir)
        cmd.append(f"--macos-app-icon={resolved_icon if resolved_icon else 'none'}")

        # Bundle redis binary into core app for zero-dependency demo runs.
        if target.name in {"core", "core-gui"} and redis_binary is not None:
            stage_dir = output_dir / ".bundle"
            stage_dir.mkdir(parents=True, exist_ok=True)
            staged_redis = stage_dir / "redis-server"
            shutil.copy2(redis_binary, staged_redis)
            staged_redis.chmod(0o755)
            cmd.append(f"--include-data-files={staged_redis}=redis-server")
    elif onefile:
        cmd.append("--onefile")

    if target.name in {"core-gui", "filesystem-gui"}:
        cmd.append("--enable-plugin=tk-inter")

    if macos_sign_identity:
        cmd.append(f"--macos-sign-identity={macos_sign_identity}")

    cmd.append(str(target.source))
    subprocess.run(cmd, check=True, cwd=_repo_root())


def _app_bundle_path(output_dir: Path, target: BuildTarget) -> Path:
    return output_dir / f"{target.source.stem}.app"


@app.callback()
def main() -> None:
    """Nuitka builder for local DSX-Connect CLIs."""


@app.command("build")
def cmd_build(
    target: str = typer.Argument("all", help="target: core | filesystem | core-gui | filesystem-gui | all"),
    output_dir: str = typer.Option("dist/local-binaries", "--output-dir", help="output dir for built binaries"),
    onefile: bool = typer.Option(True, "--onefile/--no-onefile", help="build onefile binary"),
    macos_sign_identity: str | None = typer.Option(
        None,
        "--macos-sign-identity",
        help="optional macOS codesign identity",
    ),
) -> None:
    if shutil.which(sys.executable) is None:
        raise typer.BadParameter("python executable not found")
    if not _nuitka_module_available():
        print("Nuitka is not installed in this venv.")
        print("Install with: pip install nuitka")
        raise typer.Exit(code=1)

    selected = _build_selected_targets(target)
    out = Path(output_dir)
    for item in selected:
        print(f"building binary target={item.name} source={item.source}")
        _run_build(
            target=item,
            output_dir=out,
            onefile=onefile,
            macos_sign_identity=macos_sign_identity,
            app_bundle=False,
            app_name_prefix="",
            app_icon=None,
            redis_binary=None,
        )

    print(f"done: output at {out.resolve()}")


@app.command("build-app")
def cmd_build_app(
    target: str = typer.Argument("all", help="target: core | filesystem | core-gui | filesystem-gui | all"),
    output_dir: str = typer.Option("dist/local-apps", "--output-dir", help="output dir for app bundles"),
    app_name_prefix: str = typer.Option("DSXConnectLocal", "--app-name-prefix", help="prefix for .app bundle names"),
    app_icon: str | None = typer.Option(None, "--app-icon", help="optional .icns/.png/.svg path"),
    redis_binary: str | None = typer.Option(None, "--redis-binary", help="optional redis-server path to bundle"),
    macos_sign_identity: str | None = typer.Option(
        None,
        "--macos-sign-identity",
        help="optional macOS codesign identity",
    ),
) -> None:
    if platform.system() != "Darwin":
        print("build-app is macOS-only (requires --macos-create-app-bundle).")
        raise typer.Exit(code=1)

    if shutil.which(sys.executable) is None:
        raise typer.BadParameter("python executable not found")
    if not _nuitka_module_available():
        print("Nuitka is not installed in this venv.")
        print("Install with: pip install nuitka")
        raise typer.Exit(code=1)

    selected = _build_selected_targets(target)
    out = Path(output_dir)
    resolved_redis = _resolve_redis_binary(redis_binary)
    for item in selected:
        print(f"building app target={item.name} source={item.source}")
        _run_build(
            target=item,
            output_dir=out,
            onefile=False,
            macos_sign_identity=macos_sign_identity,
            app_bundle=True,
            app_name_prefix=app_name_prefix,
            app_icon=app_icon,
            redis_binary=resolved_redis,
        )

    print(f"done: app bundles at {out.resolve()}")


@app.command("build-pkg")
def cmd_build_pkg(
    target: str = typer.Argument("core-gui", help="target: core | filesystem | core-gui | filesystem-gui | all"),
    app_output_dir: str = typer.Option("dist/local-apps", "--app-output-dir", help="location of built .app bundles"),
    output_dir: str = typer.Option("dist/local-pkg", "--output-dir", help="where to write .pkg"),
    package_name: str = typer.Option("DSXConnectLocal", "--package-name", help="base package filename"),
    version: str = typer.Option("1.0.0", "--version", help="package version"),
    identifier: str = typer.Option(
        "com.deepinstinct.dsxconnect.local",
        "--identifier",
        help="base package identifier",
    ),
    rebuild_apps: bool = typer.Option(True, "--rebuild-apps/--no-rebuild-apps", help="build app bundles before packaging"),
    app_name_prefix: str = typer.Option("DSXConnectLocal", "--app-name-prefix", help="prefix for .app bundle names"),
    app_icon: str | None = typer.Option(None, "--app-icon", help="optional .icns/.png/.svg path"),
    redis_binary: str | None = typer.Option(None, "--redis-binary", help="optional redis-server path to bundle"),
    macos_sign_identity: str | None = typer.Option(
        None,
        "--macos-sign-identity",
        help="optional macOS codesign identity for app build",
    ),
    pkg_sign_identity: str | None = typer.Option(
        None,
        "--pkg-sign-identity",
        help="optional macOS installer signing identity for final .pkg",
    ),
) -> None:
    if platform.system() != "Darwin":
        print("build-pkg is macOS-only.")
        raise typer.Exit(code=1)

    if shutil.which("pkgbuild") is None or shutil.which("productbuild") is None:
        print("pkgbuild/productbuild not found (install Xcode command line tools).")
        raise typer.Exit(code=1)

    selected = _build_selected_targets(target)
    apps_out = Path(app_output_dir)

    if rebuild_apps:
        if not _nuitka_module_available():
            print("Nuitka is not installed in this venv.")
            print("Install with: pip install nuitka")
            raise typer.Exit(code=1)
        resolved_redis = _resolve_redis_binary(redis_binary)
        for item in selected:
            print(f"building app target={item.name} source={item.source}")
            _run_build(
                target=item,
                output_dir=apps_out,
                onefile=False,
                macos_sign_identity=macos_sign_identity,
                app_bundle=True,
                app_name_prefix=app_name_prefix,
                app_icon=app_icon,
                redis_binary=resolved_redis,
            )

    app_paths = [_app_bundle_path(apps_out, t) for t in selected]
    missing = [p for p in app_paths if not p.exists()]
    if missing:
        print("missing app bundle(s):")
        for item in missing:
            print(f"  - {item}")
        print("build apps first or pass --rebuild-apps")
        raise typer.Exit(code=1)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stage_root = out_dir / ".pkgroot"
    stage_apps = stage_root / "Applications"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_apps.mkdir(parents=True, exist_ok=True)

    for app_path in app_paths:
        shutil.copytree(app_path, stage_apps / app_path.name, dirs_exist_ok=True)

    component_pkg = out_dir / f"{package_name}.component.pkg"
    final_pkg = out_dir / f"{package_name}-{target}-{version}.pkg"

    subprocess.run(
        [
            "pkgbuild",
            "--root",
            str(stage_root),
            "--identifier",
            f"{identifier}.component",
            "--version",
            version,
            "--install-location",
            "/",
            str(component_pkg),
        ],
        check=True,
    )

    productbuild_cmd = [
        "productbuild",
    ]
    if pkg_sign_identity:
        productbuild_cmd.extend(["--sign", pkg_sign_identity])
    productbuild_cmd.extend([
        "--package",
        str(component_pkg),
        str(final_pkg),
    ])

    subprocess.run(
        productbuild_cmd,
        check=True,
    )

    print(f"done: pkg at {final_pkg.resolve()}")


if __name__ == "__main__":
    app()
