import os
import re
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from invoke import task, Exit
from concurrent.futures import ThreadPoolExecutor, as_completed
## Note: test-related imports and tasks have been moved to test-tasks.py

# ---------- Edit me ----------
# Explicit, human-edited list of connectors (folder names under ./connectors)
# Flip enabled=True/False or add/remove lines as you like.
CONNECTORS_CONFIG = [
    {"name": "aws_s3", "enabled": True},
    {"name": "azure_blob_storage", "enabled": True},
    {"name": "filesystem", "enabled": True},
    {"name": "google_cloud_storage", "enabled": True},
    {"name": "sharepoint", "enabled": True},
    {"name": "m365_mail", "enabled": True},
    {"name": "onedrive", "enabled": True}
]
# ---------- /Edit me ----------

# Regex to extract X.Y.Z from a VERSION = "X.Y.Z" line
# Match common version constants in version.py files
# e.g., VERSION = "1.2.3" or DSX_CONNECT_VERSION = "1.2.3" or CONNECTOR_VERSION = "1.2.3"
VERSION_PATTERN = re.compile(r"(?:VERSION|DSX_CONNECT_VERSION|CONNECTOR_VERSION)\s*=\s*[\"'](\d+\.\d+\.\d+)[\"']")

# Base directories
PROJECT_ROOT = Path(__file__).parent.resolve()
CORE_VERSION_FILE = PROJECT_ROOT / "dsx_connect" / "version.py"
QUICKSTART_PATH = PROJECT_ROOT / "docs" / "deployment" / "kubernetes" / "getting-started-quickstart.md"
CONNECTORS_DIR = PROJECT_ROOT / "connectors"
DEPLOYMENT_DIR = "docker_bundle"


def read_version_file(path: Path) -> str:
    """Read and return the version string from a version.py file."""
    content = path.read_text()
    match = VERSION_PATTERN.search(content)
    if not match:
        raise ValueError(f"No VERSION found in {path}")
    return match.group(1)


def _sync_chart_yaml(chart_path: Path, version: str) -> None:
    """Ensure Chart.yaml has matching version/appVersion."""
    if not chart_path.exists():
        raise FileNotFoundError(f"Chart.yaml not found at {chart_path}")
    lines = chart_path.read_text().splitlines()
    version_idx = None
    app_idx = None
    for idx, line in enumerate(lines):
        if line.startswith("version:"):
            lines[idx] = f"version: {version}"
            version_idx = idx
        elif line.startswith("appVersion:"):
            lines[idx] = f'appVersion: "{version}"'
            app_idx = idx
    if app_idx is None:
        insert_at = version_idx + 1 if version_idx is not None else len(lines)
        lines.insert(insert_at, f'appVersion: "{version}"')
    chart_path.write_text("\n".join(lines) + "\n")


from connectors.framework.tasks.common import (
    clean_export as _clean_export_impl,
    release_connector_no_bump as _release_connector_no_bump_impl,
    zip_export as _zip_export_impl,
)

# Default OCI Helm repo base (Docker Hub requires namespace-only base; chart name becomes the repo)
DEFAULT_HELM_REPO = "oci://registry-1.docker.io/dsxconnect"


@task
def release_connector_nobump(c, name: str, repo_uname: str = "dsxconnect"):
    """Build+push a connector image without bumping version (CI-friendly)."""
    _release_connector_no_bump_impl(c, project_slug=name, repo_uname=repo_uname)


@task
def sync_core_chart_version(c):
    """
    Sync dsx-connect Helm Chart.yaml version/appVersion with dsx_connect/version.py.
    Run this before packaging/pushing the core Helm chart to avoid drift.
    """
    version = read_version_file(CORE_VERSION_FILE)
    chart_path = PROJECT_ROOT / "dsx_connect" / "deploy" / "helm" / "Chart.yaml"
    _sync_chart_yaml(chart_path, version)
    print(f"[sync] Updated {chart_path} to version {version}")


@task
def helm_release(
    c,
    repo: str = DEFAULT_HELM_REPO,
    only: str = "",
    skip: str = "",
    include_core: bool = True,
    parallel: bool = False,
    max_workers: int = 4,
    continue_on_error: bool = True,
    dry_run: bool = False,
):
    """
    Helm release for the project:
    - Runs dsx_connect helm-release (unless --include-core=false).
    - Runs each selected connector's helm-release.

    Examples:
      inv helm-release                      # core + all enabled connectors
      inv helm-release --only=azure_blob_storage,filesystem
      inv helm-release --skip=google_cloud_storage
      inv helm-release --repo=oci://registry-1.docker.io/dsxconnect
    """
    import os as _os
    if include_core:
        version = read_version_file(CORE_VERSION_FILE)
        chart_path = PROJECT_ROOT / "dsx_connect" / "deploy" / "helm" / "Chart.yaml"
        _sync_chart_yaml(chart_path, version)
        print(f"[helm-release] Core Chart.yaml synced to {version}")
        print("=== Helm release: core (dsx_connect) ===")
        repo = repo or _os.environ.get("HELM_REPO", DEFAULT_HELM_REPO)
        # Pushing charts to the 'dsxconnect' namespace is safe because chart names carry a '-chart' suffix.
        core_cmd = f"invoke helm-release --repo={repo}"
        code = _run(c, core_cmd, cwd=PROJECT_ROOT / "dsx_connect", dry_run=dry_run)
        if code != 0:
            raise Exit(code)

    chosen = _select_connectors(only=only, skip=skip, include_disabled=False)

    if not chosen:
        print("[helm-release] No connectors selected.")
        return

    print("=== Helm release: connectors ===")
    # Build work list, skipping connectors without a Helm chart directory
    work: list[tuple[str, str]] = []
    for n in chosen:
        chart_dir = CONNECTORS_DIR / n / "deploy" / "helm"
        if not chart_dir.exists():
            print(f"[helm-release] Skipping {n}: no Helm chart dir at {chart_dir}")
            continue
        eff_repo = repo or _os.environ.get("HELM_REPO", DEFAULT_HELM_REPO)
        cmd = f"invoke helm-release --repo={eff_repo}"
        work.append((n, cmd))
    errors: list[tuple[str, int]] = []

    def _do(n: str, cmd: str) -> tuple[str, int]:
        code = _run(c, cmd, cwd=CONNECTORS_DIR / n, dry_run=dry_run)
        return (n, code)

    if parallel:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_do, n, cmd): n for n, cmd in work}
            for fut in as_completed(futures):
                n, code = fut.result()
                if code != 0:
                    print(f"[helm-release] FAILED: {n} (exit {code})")
                    errors.append((n, code))
                    if not continue_on_error:
                        raise Exit(code)
    else:
        for n, cmd in work:
            _, code = _do(n, cmd)
            if code != 0:
                errors.append((n, code))
                if not continue_on_error:
                    raise Exit(code)

    if errors:
        bad = ", ".join([f"{n}:{code}" for n, code in errors])
        raise Exit(f"Some helm releases failed: {bad}", code=1)


@task
def generate_manifest(c, out: str = "versions.json"):
    """
    Scan the core and connector version.py files, write a JSON manifest of their versions.
    """
    manifest = {}
    # Core
    manifest["dsx_connect"] = read_version_file(CORE_VERSION_FILE)
    # Connectors (manifest still scans actual dirs so it's accurate even if disabled)
    if CONNECTORS_DIR.exists():
        for connector_path in CONNECTORS_DIR.iterdir():
            version_file = connector_path / "version.py"
            if version_file.exists():
                manifest[connector_path.name] = read_version_file(version_file)
    # Write manifest
    (PROJECT_ROOT / out).write_text(json.dumps(manifest, indent=2))
    print(f"Manifest written to {out}")


def _update_quickstart_versions(manifest: dict[str, str]) -> None:
    """Update quickstart defaults that mirror release versions."""
    if not QUICKSTART_PATH.exists():
        print(f"[quickstart] Skipping update; not found: {QUICKSTART_PATH}")
        return

    dsx_version = manifest.get("dsx_connect")
    aws_version = manifest.get("aws_s3")

    if not dsx_version and not aws_version:
        print("[quickstart] No matching versions found in manifest.")
        return

    text = QUICKSTART_PATH.read_text()
    if dsx_version:
        text = re.sub(
            r'(data-var-input="DSX_CONNECT_VERSION"\s+value=")[^"]+(")',
            rf"\g<1>{dsx_version}\2",
            text,
        )
    if aws_version:
        text = re.sub(
            r'(data-var-input="AWS_CONNECTOR_VERSION"\s+value=")[^"]+(")',
            rf"\g<1>{aws_version}\2",
            text,
        )

    QUICKSTART_PATH.write_text(text)
    print(f"[quickstart] Updated {QUICKSTART_PATH}")


def _configured_names(include_disabled: bool = False) -> list[str]:
    names = []
    for cfg in CONNECTORS_CONFIG:
        if include_disabled or cfg.get("enabled", True):
            names.append(cfg["name"])
    return names


def _select_connectors(*, only: str = "", skip: str = "", include_disabled: bool = False) -> list[str]:
    chosen = _configured_names(include_disabled=include_disabled)

    if only:
        wanted = {n.strip() for n in only.split(",") if n.strip()}
        unknown = wanted - set(_configured_names(include_disabled=True))
        if unknown:
            raise Exit(f"Unknown connector(s) in --only: {', '.join(sorted(unknown))}", code=2)
        chosen = [n for n in chosen if n in wanted]

    if skip:
        banned = {n.strip() for n in skip.split(",") if n.strip()}
        unknown = banned - set(_configured_names(include_disabled=True))
        if unknown:
            raise Exit(f"Unknown connector(s) in --skip: {', '.join(sorted(unknown))}", code=2)
        chosen = [n for n in chosen if n not in banned]

    return chosen


def _connector_image_name(name: str) -> str:
    return name.replace("_", "-") + "-connector"


def _read_connector_version(name: str) -> str:
    version_file = CONNECTORS_DIR / name / "version.py"
    if not version_file.exists():
        raise Exit(f"No version.py found for connector '{name}'", code=2)
    return read_version_file(version_file)


def _connector_compose_file(name: str) -> Path:
    image_name = _connector_image_name(name)
    return CONNECTORS_DIR / name / "deploy" / "docker" / f"docker-compose-{image_name}.yaml"


def _compose_state_dir(name: str) -> Path:
    return Path.home() / ".dsx-connect-local" / f"{name}-compose"


def _connector_image_env_var(name: str) -> str:
    return {
        "aws_s3": "AWS_S3_IMAGE",
        "azure_blob_storage": "AZURE_BLOB_IMAGE",
        "filesystem": "FILESYSTEM_IMAGE",
        "google_cloud_storage": "GCS_IMAGE",
        "sharepoint": "SHAREPOINT_IMAGE",
        "m365_mail": "M365_IMAGE",
        "onedrive": "ONEDRIVE_IMAGE",
        "salesforce": "SALESFORCE_IMAGE",
    }[name]


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    env: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env[key] = value
    return env


def _compose_env_for_selection(chosen: list[str]) -> dict[str, str]:
    env = _load_env_file(_compose_state_dir("dsx-connect") / ".env.local")
    for name in chosen:
        env.update(_load_env_file(_compose_state_dir(_connector_image_name(name)) / ".env.local"))
    return env


def _translate_localhost_url_for_compose(url: str) -> str:
    return re.sub(r"//(?:127\.0\.0\.1|localhost)(?=[:/]|$)", "//host.docker.internal", url)


def _normalize_compose_env(env: dict[str, str], *, include_dsxa: bool) -> dict[str, str]:
    normalized = dict(env)

    # Let the compose core stack use its built-in internal Redis wiring.
    for key in (
        "DSXCONNECT_REDIS_URL",
        "DSXCONNECT_RESULTS_DB",
        "DSXCONNECT_WORKERS__BROKER",
        "DSXCONNECT_WORKERS__BACKEND",
    ):
        normalized.pop(key, None)

    # Let connector compose files use their internal service-name defaults.
    for key in (
        "DSXCONNECTOR_CONNECTOR_URL",
        "DSXCONNECTOR_DSX_CONNECT_URL",
    ):
        normalized.pop(key, None)

    # Containers should use their mounted in-container data directories, not desktop host paths.
    normalized["DSXCONNECTOR_DATA_DIR"] = "/app/data"

    # Desktop relative cert paths are not valid in the compose container layout.
    for key in (
        "DSXCONNECTOR_TLS_CERTFILE",
        "DSXCONNECTOR_TLS_KEYFILE",
        "DSXCONNECTOR_CA_BUNDLE",
    ):
        normalized.pop(key, None)

    if include_dsxa:
        normalized.pop("DSXCONNECT_SCANNER__SCAN_BINARY_URL", None)
    else:
        scanner_url = normalized.get("DSXCONNECT_SCANNER__SCAN_BINARY_URL")
        if scanner_url:
            normalized["DSXCONNECT_SCANNER__SCAN_BINARY_URL"] = _translate_localhost_url_for_compose(scanner_url)

    return normalized


def _remove_local_image_if_present(c, image_ref: str, *, dry_run: bool = False) -> None:
    inspect = c.run(f"docker image inspect {image_ref}", warn=True, hide=True)
    if inspect.exited != 0:
        return
    cmd = f"docker image rm -f {image_ref}"
    code = _run(c, cmd, dry_run=dry_run)
    if code != 0:
        raise Exit(f"Failed removing existing local image {image_ref}", code=code)


def _tag_local_image(c, source_ref: str, target_ref: str, *, dry_run: bool = False) -> None:
    code = _run(c, f"docker tag {source_ref} {target_ref}", dry_run=dry_run)
    if code != 0:
        raise Exit(f"Failed tagging local image {source_ref} -> {target_ref}", code=code)


def _build_inv_cmd_for_module(modpath: str, extra: str = "") -> str:
    extra = extra.strip()
    return f"invoke -c {modpath} release{(' ' + extra) if extra else ''}"


def _build_core_cmd(extra: str = "") -> str:
    # Run the default 'tasks.py' inside dsx_connect by changing cwd
    extra = extra.strip()
    return f"invoke release{(' ' + extra) if extra else ''}"


def _is_forbidden_env_file(path: str) -> bool:
    """
    Return True when a path in an image layer looks like a secret-bearing local
    config file that should never be baked into container layers.
    """
    name = Path(path).name
    if name == ".dev.env":
        return True
    if name.endswith(".dev.env"):
        return True
    if name == ".env":
        return True
    if name.startswith(".env."):
        return True
    # GCP/GCS service-account key file conventions used in local setups.
    if name in {"gcp-sa.json", "gcs-sa.json"}:
        return True
    if name.endswith("-sa.json"):
        return True
    return False


def _audit_image_layers_for_env_files(image_ref: str) -> list[str]:
    """
    Save an image and inspect all layer tar entries for forbidden env file names.
    Returns matching paths (deduplicated, sorted).
    """
    import subprocess

    hits: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="img-audit-") as td:
        save_tar = Path(td) / "image.tar"
        subprocess.run(["docker", "save", image_ref, "-o", str(save_tar)], check=True)

        with tarfile.open(save_tar, "r") as img_tf:
            manifest_member = img_tf.extractfile("manifest.json")
            if manifest_member is None:
                raise RuntimeError(f"manifest.json missing in docker save tar for {image_ref}")
            manifest = json.loads(manifest_member.read().decode("utf-8"))

            # docker save format: manifest is a list; each item has Layers[]
            layer_paths: list[str] = []
            for item in manifest:
                layer_paths.extend(item.get("Layers", []))

            for layer_path in layer_paths:
                layer_member = img_tf.extractfile(layer_path)
                if layer_member is None:
                    continue
                with tarfile.open(fileobj=layer_member, mode="r:*") as layer_tf:
                    for member in layer_tf.getmembers():
                        if not member.isfile():
                            continue
                        p = member.name.lstrip("./")
                        if _is_forbidden_env_file(p):
                            hits.add(p)
    return sorted(hits)


@task(help={
    "repo": "Image repository/namespace prefix (e.g. dsxconnect). Use empty string for local-only names.",
    "tag": "Image tag to audit (default: latest).",
    "pull": "Pull images before audit (true/false).",
})
def audit_connector_images(c, repo: str = "dsxconnect", tag: str = "latest", pull: bool = True):
    """
    Audit ALL enabled connector images for baked env secret files in any image layer.
    Fails if any forbidden env files (e.g. .dev.env, .env, .env.*, *.dev.env) are found.
    """
    selected = _configured_names(include_disabled=False)
    if not selected:
        print("[audit] No enabled connectors configured.")
        return

    pull_bool = str(pull).strip().lower() in {"1", "true", "yes", "y"}
    failures: list[tuple[str, list[str]]] = []

    for slug in selected:
        image_name = slug.replace("_", "-") + "-connector"
        image_ref = f"{repo}/{image_name}:{tag}" if repo else f"{image_name}:{tag}"
        print(f"[audit] Checking {image_ref}")

        if pull_bool:
            pull_res = c.run(f"docker pull {image_ref}", warn=True, hide=True)
            if pull_res.exited != 0:
                raise Exit(f"[audit] Unable to pull image: {image_ref}", code=pull_res.exited)
        else:
            has_local = c.run(f"docker image inspect {image_ref}", warn=True, hide=True).exited == 0
            if not has_local:
                raise Exit(f"[audit] Local image not found: {image_ref}", code=2)

        try:
            hits = _audit_image_layers_for_env_files(image_ref)
        except Exception as e:
            raise Exit(f"[audit] Failed scanning {image_ref}: {e}", code=3)

        if hits:
            failures.append((image_ref, hits))
            print(f"[audit] FAIL {image_ref}: found forbidden files in layers -> {hits}")
        else:
            print(f"[audit] PASS {image_ref}")

    if failures:
        lines = ["[audit] Secret file leak detected in image layers:"]
        for ref, hits in failures:
            lines.append(f"  - {ref}: {', '.join(hits)}")
        raise Exit("\n".join(lines), code=1)
    print("[audit] All connector images passed.")


@task(help={
    "move": "Remove original repo-local .dev.env files after successful copy (true/false).",
    "overwrite": "Overwrite target ~/.dsx-connect-local/<name>/.env.local if it exists (true/false).",
    "include_core": "Also migrate dsx_connect/.dev.env (true/false).",
})
def migrate_dev_envs(c, move: bool = True, overwrite: bool = False, include_core: bool = True):
    """
    Migrate repo-local .dev.env files to ~/.dsx-connect-local/<name>/.env.local.
    """
    move_bool = str(move).strip().lower() in {"1", "true", "yes", "y"}
    overwrite_bool = str(overwrite).strip().lower() in {"1", "true", "yes", "y"}
    include_core_bool = str(include_core).strip().lower() in {"1", "true", "yes", "y"}

    sources: list[tuple[str, Path]] = []
    for cfg in CONNECTORS_CONFIG:
        slug = cfg["name"]
        src = PROJECT_ROOT / "connectors" / slug / ".dev.env"
        if src.exists():
            sources.append((slug, src))
    if include_core_bool:
        core_src = PROJECT_ROOT / "dsx_connect" / ".dev.env"
        if core_src.exists():
            sources.append(("dsx_connect", core_src))

    if not sources:
        print("[migrate_dev_envs] No repo-local .dev.env files found.")
        return

    moved = 0
    copied = 0
    skipped = 0
    for name, src in sources:
        dst_dir = Path.home() / ".dsx-connect-local" / name
        dst = dst_dir / ".env.local"
        dst_dir.mkdir(parents=True, exist_ok=True)

        if dst.exists() and not overwrite_bool:
            print(f"[migrate_dev_envs] SKIP {src} -> {dst} (target exists)")
            skipped += 1
            continue

        content = src.read_text(encoding="utf-8")
        dst.write_text(content, encoding="utf-8")
        copied += 1
        if move_bool:
            src.unlink()
            moved += 1
            print(f"[migrate_dev_envs] MOVED {src} -> {dst}")
        else:
            print(f"[migrate_dev_envs] COPIED {src} -> {dst}")

    print(f"[migrate_dev_envs] done: copied={copied}, moved={moved}, skipped={skipped}")



def _connector_cmd(name: str, extra: str = "") -> str:
    # Connectors run "invoke release" from within their folder (they each define a 'release' task).
    extra = extra.strip()
    return f"invoke release{(' ' + extra) if extra else ''}"


def _run(c, cmd: str, *, cwd: Path | None = None, dry_run: bool = False, env: dict | None = None) -> int:
    print(f"[release] {cmd} (cwd={cwd or PROJECT_ROOT})")
    if dry_run:
        return 0
    run_env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT), **(env or {})}
    if cwd:
        with c.cd(str(cwd)):
            r = c.run(cmd, hide=False, warn=True, env=run_env)
    else:
        r = c.run(cmd, hide=False, warn=True, env=run_env)
    return r.exited


@task
def release_core(c, extra: str = "", dry_run: bool = False):
    """Run the core dsx_connect release task (passes through any 'extra' flags)."""
    cmd = _build_core_cmd(extra=extra)
    code = _run(
        c,
        cmd,
        cwd=PROJECT_ROOT / "dsx_connect",  # <<< key change
        dry_run=dry_run,
    )
    if code != 0:
        raise Exit(code)



@task
def release_connector(c, name: str, extra: str = "", dry_run: bool = False):
    """Run release for a single connector by name (e.g., inv release-connector --name=aws_s3)."""
    if name not in _configured_names(include_disabled=True):
        raise Exit(f"Connector '{name}' is not in CONNECTORS_CONFIG.", code=2)
    cmd = _connector_cmd(name, extra=extra)
    code = _run(c, cmd, cwd=CONNECTORS_DIR / name, dry_run=dry_run)
    if code != 0:
        raise Exit(code)


@task
def connectors_list(c, all: bool = False):
    """
    Print the configured connector list.
    Use --all to include disabled ones.
    """
    names = _configured_names(include_disabled=all)
    print("Configured connectors:")
    for cfg in CONNECTORS_CONFIG:
        if cfg["name"] in names:
            mark = "✅" if cfg.get("enabled", True) else "⛔"
            print(f"  {mark} {cfg['name']}")


@task
def release_connectors(
        c,
        only: str = "",            # CSV of connector names to run (overrides enabled list)
        skip: str = "",            # CSV of connector names to skip
        extra: str = "",           # extra args passed to each connector's 'release' (e.g., "--bump=patch --push")
        parallel: bool = False,
        max_workers: int = 4,
        continue_on_error: bool = True,
        dry_run: bool = False,
):
    """
    Release for many connectors based on the explicit CONNECTORS_CONFIG list.
    - By default runs all connectors with enabled=True.
    - Use --only to run a subset:   inv release-connectors --only=aws_s3,filesystem
    - Use --skip to exclude some:   inv release-connectors --skip=google_cloud_storage
    """
    chosen = _select_connectors(only=only, skip=skip, include_disabled=False)

    if not chosen:
        print("[release] No connectors selected.")
        return

    work = [(n, _connector_cmd(n, extra=extra)) for n in chosen]
    errors: list[tuple[str, int]] = []

    def _do(n: str, cmd: str) -> tuple[str, int]:
        code = _run(c, cmd, cwd=CONNECTORS_DIR / n, dry_run=dry_run)
        return (n, code)

    if parallel:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_do, n, cmd): n for n, cmd in work}
            for fut in as_completed(futures):
                n, code = fut.result()
                if code != 0:
                    print(f"[release] FAILED: {n} (exit {code})")
                    errors.append((n, code))
                    if not continue_on_error:
                        raise Exit(code)
    else:
        for n, cmd in work:
            _, code = _do(n, cmd)
            if code != 0:
                errors.append((n, code))
                if not continue_on_error:
                    raise Exit(code)

    if errors:
        bad = ", ".join([f"{n}:{code}" for n, code in errors])
        raise Exit(f"Some releases failed: {bad}", code=1)


## Note: test tasks moved to test-tasks.py. Use: invoke -c test-tasks <task>


@task(pre=[generate_manifest])
def release_all(
        c,
        extra_core: str = "",
        extra_connectors: str = "",
        only: str = "",
        skip: str = "",
        parallel: bool = False,
        dry_run: bool = False,
):
    """
    Official release path for core + selected connectors. Uses generate_manifest first.

    This path bumps versions, pushes images, and publishes Helm charts. Use
    `build-all-local`, `deploy-all-local`, and `push-all-dev` for the normal
    local/dev workflows instead.

    You can restrict connectors with --only/--skip (same semantics as release-connectors).
    """
    print("=== Releasing core (dsx_connect) ===")
    release_core(c, extra=extra_core, dry_run=dry_run)
    print("=== Releasing connectors ===")
    release_connectors(
        c,
        only=only,
        skip=skip,
        extra=extra_connectors,
        parallel=parallel,
        dry_run=dry_run,
    )
    # After image releases, perform Helm releases for core + selected connectors
    helm_release(c, only=only, skip=skip, include_core=True, parallel=parallel, dry_run=dry_run)
    if not dry_run:
        manifest = json.loads((PROJECT_ROOT / "versions.json").read_text())
        _update_quickstart_versions(manifest)


@task
def build_all(
        c,
        extra_core: str = "",
        extra_connectors: str = "",
        only: str = "",
        skip: str = "",
        parallel: bool = False,
        dry_run: bool = False,
):
    """
    Build core + selected connectors locally (no push).
    Pass extra args to underlying build via --extra-core/--extra-connectors.
    """
    print("=== Building core (dsx_connect) ===")
    core_cmd = f"invoke build{(' ' + extra_core) if extra_core else ''}"
    code = _run(c, core_cmd, cwd=PROJECT_ROOT / "dsx_connect", dry_run=dry_run)
    if code != 0:
        raise Exit(code)

    chosen = _select_connectors(only=only, skip=skip, include_disabled=False)

    if not chosen:
        print("[build_all] No connectors selected.")
        return

    print("=== Building connectors ===")
    errors: list[tuple[str, int]] = []

    def _build_connector(name: str) -> int:
        cmd = f"invoke build{(' ' + extra_connectors) if extra_connectors else ''}"
        return _run(c, cmd, cwd=CONNECTORS_DIR / name, dry_run=dry_run)

    if parallel:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(4, len(chosen))) as ex:
            futs = {ex.submit(_build_connector, n): n for n in chosen}
            for fut in as_completed(futs):
                n = futs[fut]
                code = fut.result()
                if code != 0:
                    print(f"[build_all] FAILED: {n} (exit {code})")
                    errors.append((n, code))
    else:
        for n in chosen:
            code = _build_connector(n)
            if code != 0:
                errors.append((n, code))

    if errors:
        bad = ", ".join([f"{n}:{code}" for n, code in errors])
        raise Exit(f"Some connector builds failed: {bad}", code=1)


@task
def build_all_local(
        c,
        extra_core: str = "",
        extra_connectors: str = "",
        only: str = "",
        skip: str = "",
        parallel: bool = False,
        dry_run: bool = False,
):
    """
    Build core + selected connectors into the local Docker daemon only.

    This is the normal Colima/local-k3s image build path. It does not push images
    or package/push Helm charts. Existing local images for the current version are
    removed first so local code changes always rebuild without requiring a version bump.
    """
    core_version = read_version_file(CORE_VERSION_FILE)
    _remove_local_image_if_present(c, f"dsx-connect:{core_version}", dry_run=dry_run)

    chosen = _select_connectors(only=only, skip=skip, include_disabled=False)
    for name in chosen:
        version = _read_connector_version(name)
        _remove_local_image_if_present(c, f"{_connector_image_name(name)}:{version}", dry_run=dry_run)

    build_all(
        c,
        extra_core=extra_core,
        extra_connectors=extra_connectors,
        only=only,
        skip=skip,
        parallel=parallel,
        dry_run=dry_run,
    )

    for name in chosen:
        version = _read_connector_version(name)
        image_name = _connector_image_name(name)
        _tag_local_image(
            c,
            f"{image_name}:{version}",
            f"{image_name}:latest",
            dry_run=dry_run,
        )


@task(help={
    "namespace": "Kubernetes namespace for local deployment.",
    "release_prefix": "Prefix used for Helm release names.",
    "image_pull_policy": "Image pull policy for local images (Never or IfNotPresent).",
    "extra_core": "Extra raw args appended to the core helm upgrade/install command.",
    "extra_connectors": "Extra raw args appended to connector helm upgrade/install commands.",
    "only": "Connectors to deploy, comma-separated with no spaces: aws_s3,azure_blob_storage,filesystem,google_cloud_storage,sharepoint,m365_mail,onedrive.",
    "skip": "Connectors to skip, comma-separated with no spaces: aws_s3,azure_blob_storage,filesystem,google_cloud_storage,sharepoint,m365_mail,onedrive.",
})
def deploy_all_local(
        c,
        namespace: str = "default",
        release_prefix: str = "",
        only: str = "",
        skip: str = "",
        image_pull_policy: str = "Never",
        extra_core: str = "",
        extra_connectors: str = "",
        dry_run: bool = False,
):
    """
    Deploy core + selected connectors to the local cluster from local chart directories.

    This uses local image names and local chart paths, not OCI chart repos.
    """
    core_version = read_version_file(CORE_VERSION_FILE)
    core_release = f"{release_prefix}dsx-connect" if release_prefix else "dsx-connect"
    core_chart_dir = PROJECT_ROOT / "dsx_connect" / "deploy" / "helm"
    _sync_chart_yaml(core_chart_dir / "Chart.yaml", core_version)
    dep_code = _run(c, f"helm dependency build {core_chart_dir}", dry_run=dry_run)
    if dep_code != 0:
        raise Exit(dep_code)
    core_cmd = (
        f"helm upgrade --install {core_release} {core_chart_dir} "
        f"--namespace {namespace} --create-namespace "
        f"--set-string global.image.repository=dsx-connect "
        f"--set-string global.image.tag={core_version} "
        f"--set-string global.image.pullPolicy={image_pull_policy}"
    )
    if extra_core:
        core_cmd += f" {extra_core.strip()}"
    code = _run(c, core_cmd, dry_run=dry_run)
    if code != 0:
        raise Exit(code)

    chosen = _select_connectors(only=only, skip=skip, include_disabled=False)
    if not chosen:
        print("[deploy_all_local] No connectors selected.")
        return

    for name in chosen:
        chart_dir = CONNECTORS_DIR / name / "deploy" / "helm"
        if not chart_dir.exists():
            print(f"[deploy_all_local] Skipping {name}: no Helm chart dir at {chart_dir}")
            continue

        version = _read_connector_version(name)
        image_name = _connector_image_name(name)
        release_name = f"{release_prefix}{image_name}" if release_prefix else image_name
        cmd = (
            f"helm upgrade --install {release_name} {chart_dir} "
            f"--namespace {namespace} --create-namespace "
            f"--set-string image.repository={image_name} "
            f"--set-string image.tag={version} "
            f"--set-string image.pullPolicy={image_pull_policy}"
        )
        if extra_connectors:
            cmd += f" {extra_connectors.strip()}"
        code = _run(c, cmd, dry_run=dry_run)
        if code != 0:
            raise Exit(code)


@task(help={
    "include_dsxa": "Also start the bundled DSXA compose stack.",
    "extra": "Extra raw args appended to the docker compose up command.",
    "only": "Connectors to deploy, comma-separated with no spaces: aws_s3,azure_blob_storage,filesystem,google_cloud_storage,sharepoint,m365_mail,onedrive.",
    "skip": "Connectors to skip, comma-separated with no spaces: aws_s3,azure_blob_storage,filesystem,google_cloud_storage,sharepoint,m365_mail,onedrive.",
})
def compose_up_local(
        c,
        only: str = "",
        skip: str = "",
        include_dsxa: bool = False,
        extra: str = "",
        dry_run: bool = False,
):
    """
    Start the local Docker Compose stack from repo compose files using local images.

    This uses the local `:latest` image tags produced by `build-all-local` and does
    not rely on Docker Hub or OCI charts.
    """
    network_cmd = "docker network inspect dsx-connect-network >/dev/null 2>&1 || docker network create dsx-connect-network"
    code = _run(c, network_cmd, dry_run=dry_run)
    if code != 0:
        raise Exit(code)

    compose_files = [
        PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "docker-compose-dsx-connect-all-services.yaml",
    ]
    if include_dsxa:
        compose_files.append(PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "docker-compose-dsxa.yaml")

    chosen = _select_connectors(only=only, skip=skip, include_disabled=False)
    raw_env = _compose_env_for_selection(chosen)
    gcs_sa_path = raw_env.get("GCS_SA_JSON_PATH", "").strip()
    if "google_cloud_storage" in chosen and (not gcs_sa_path or not Path(gcs_sa_path).expanduser().exists()):
        print("[compose_up_local] Skipping google_cloud_storage: set GCS_SA_JSON_PATH in google-cloud-storage-connector-compose/.env.local")
        chosen = [name for name in chosen if name != "google_cloud_storage"]

    for name in chosen:
        compose_path = _connector_compose_file(name)
        if not compose_path.exists():
            print(f"[compose_up_local] Skipping {name}: no compose file at {compose_path}")
            continue
        compose_files.append(compose_path)

    env = _normalize_compose_env(_compose_env_for_selection(chosen), include_dsxa=include_dsxa)
    env["DSXCONNECT_IMAGE"] = "dsx-connect:latest"
    for name in chosen:
        env[_connector_image_env_var(name)] = f"{_connector_image_name(name)}:latest"

    compose_flags = " ".join([f"-f {path}" for path in compose_files])
    cmd = f"docker compose {compose_flags} up -d"
    if extra:
        cmd += f" {extra.strip()}"
    code = _run(c, cmd, dry_run=dry_run, env=env)
    if code != 0:
        raise Exit(code)


@task(help={
    "extra": "Extra raw args appended to the docker compose up command.",
})
def compose_dsxa_up(
        c,
        extra: str = "",
        dry_run: bool = False,
):
    """
    Start only the bundled DSXA Docker Compose stack using the dsx-connect-compose env file.
    """
    network_cmd = "docker network inspect dsx-connect-network >/dev/null 2>&1 || docker network create dsx-connect-network"
    code = _run(c, network_cmd, dry_run=dry_run)
    if code != 0:
        raise Exit(code)

    compose_file = PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "docker-compose-dsxa.yaml"
    env = _load_env_file(_compose_state_dir("dsx-connect") / ".env.local")

    cmd = f"docker compose -f {compose_file} up -d"
    if extra:
        cmd += f" {extra.strip()}"
    code = _run(c, cmd, dry_run=dry_run, env=env)
    if code != 0:
        raise Exit(code)


@task(help={
    "include_dsxa": "Also stop the bundled DSXA compose stack.",
    "extra": "Extra raw args appended to the docker compose down command.",
    "only": "Connectors to stop, comma-separated with no spaces: aws_s3,azure_blob_storage,filesystem,google_cloud_storage,sharepoint,m365_mail,onedrive.",
    "skip": "Connectors to exclude from stop, comma-separated with no spaces: aws_s3,azure_blob_storage,filesystem,google_cloud_storage,sharepoint,m365_mail,onedrive.",
})
def compose_down_local(
        c,
        only: str = "",
        skip: str = "",
        include_dsxa: bool = False,
        extra: str = "",
        dry_run: bool = False,
):
    """
    Stop the local Docker Compose stack built from repo compose files.
    """
    compose_files = [
        PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "docker-compose-dsx-connect-all-services.yaml",
    ]
    if include_dsxa:
        compose_files.append(PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "docker-compose-dsxa.yaml")

    chosen = _select_connectors(only=only, skip=skip, include_disabled=False)
    raw_env = _compose_env_for_selection(chosen)
    gcs_sa_path = raw_env.get("GCS_SA_JSON_PATH", "").strip()
    if "google_cloud_storage" in chosen and (not gcs_sa_path or not Path(gcs_sa_path).expanduser().exists()):
        chosen = [name for name in chosen if name != "google_cloud_storage"]

    for name in chosen:
        compose_path = _connector_compose_file(name)
        if compose_path.exists():
            compose_files.append(compose_path)

    env = _normalize_compose_env(_compose_env_for_selection(chosen), include_dsxa=include_dsxa)
    env["DSXCONNECT_IMAGE"] = "dsx-connect:latest"
    for name in chosen:
        env[_connector_image_env_var(name)] = f"{_connector_image_name(name)}:latest"

    compose_flags = " ".join([f"-f {path}" for path in compose_files])
    cmd = f"docker compose {compose_flags} down"
    if extra:
        cmd += f" {extra.strip()}"
    code = _run(c, cmd, dry_run=dry_run, env=env)
    if code != 0:
        raise Exit(code)


@task(help={
    "extra": "Extra raw args appended to the docker compose down command.",
})
def compose_dsxa_down(
        c,
        extra: str = "",
        dry_run: bool = False,
):
    """
    Stop only the bundled DSXA Docker Compose stack.
    """
    compose_file = PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "docker-compose-dsxa.yaml"
    env = _load_env_file(_compose_state_dir("dsx-connect") / ".env.local")

    cmd = f"docker compose -f {compose_file} down"
    if extra:
        cmd += f" {extra.strip()}"
    code = _run(c, cmd, dry_run=dry_run, env=env)
    if code != 0:
        raise Exit(code)


@task(pre=[generate_manifest], help={
    "repo": "Docker image namespace/repository prefix for dev images (e.g. dsxconnect-dev).",
    "helm_repo": "OCI Helm repo for dev charts (e.g. oci://registry-1.docker.io/dsxconnect-dev).",
    "only": "Connectors to publish, comma-separated with no spaces: aws_s3,azure_blob_storage,filesystem,google_cloud_storage,sharepoint,m365_mail,onedrive.",
    "skip": "Connectors to skip, comma-separated with no spaces: aws_s3,azure_blob_storage,filesystem,google_cloud_storage,sharepoint,m365_mail,onedrive.",
})
def push_all_dev(
        c,
        repo: str = "dsxconnect-dev",
        helm_repo: str = "oci://registry-1.docker.io/dsxconnect-dev",
        only: str = "",
        skip: str = "",
        parallel: bool = False,
        dry_run: bool = False,
):
    """
    Build + push current-version images and Helm charts to a dev registry namespace.

    This path does not bump versions. It is intended for shared dev/test registries,
    not official release publication.
    """
    print("=== Building and pushing core (dsx_connect) to dev repo ===")
    code = _run(c, "invoke build", cwd=PROJECT_ROOT / "dsx_connect", dry_run=dry_run)
    if code != 0:
        raise Exit(code)
    code = _run(c, f"invoke push --repo={repo}", cwd=PROJECT_ROOT / "dsx_connect", dry_run=dry_run)
    if code != 0:
        raise Exit(code)

    chosen = _select_connectors(only=only, skip=skip, include_disabled=False)
    if chosen:
        print("=== Building and pushing connectors to dev repo ===")

        errors: list[tuple[str, int]] = []

        def _push_connector(name: str) -> tuple[str, int]:
            code = _run(
                c,
                f"invoke release-connector-nobump --name={name} --repo-uname={repo}",
                cwd=PROJECT_ROOT,
                dry_run=dry_run,
            )
            return name, code

        if parallel:
            with ThreadPoolExecutor(max_workers=min(4, len(chosen))) as ex:
                futures = {ex.submit(_push_connector, n): n for n in chosen}
                for fut in as_completed(futures):
                    n, code = fut.result()
                    if code != 0:
                        print(f"[push_all_dev] FAILED: {n} (exit {code})")
                        errors.append((n, code))
        else:
            for n in chosen:
                _, code = _push_connector(n)
                if code != 0:
                    errors.append((n, code))

        if errors:
            bad = ", ".join([f"{n}:{code}" for n, code in errors])
            raise Exit(f"Some connector dev pushes failed: {bad}", code=1)

    helm_release(
        c,
        repo=helm_repo,
        only=only,
        skip=skip,
        include_core=True,
        parallel=parallel,
        dry_run=dry_run,
    )


@task(pre=[generate_manifest])
def bundle(c):
    """
    Bundle Docker assets for core and each connector into docker_bundle/.
    Uses files directly from the repo (no staging/export).
    """
    core_version = read_version_file(CORE_VERSION_FILE)
    core_bundle = PROJECT_ROOT / DEPLOYMENT_DIR / f"dsx-connect-{core_version}"
    if core_bundle.exists():
        shutil.rmtree(core_bundle)
    core_bundle.mkdir(parents=True, exist_ok=True)
    # Core compose + env sample
    core_compose_src = PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "docker-compose-dsx-connect-all-services.yaml"
    dsxa_compose_src = PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "docker-compose-dsxa.yaml"
    env_core = PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "sample.core.env"
    env_dsxa = PROJECT_ROOT / "dsx_connect" / "deploy" / "docker" / "sample.dsxa.env"
    for src in (core_compose_src, dsxa_compose_src, env_core, env_dsxa):
        if src.exists():
            c.run(f"cp -f {src} {core_bundle}/{src.name}")
    _append_bundle_readme(core_bundle / "README.md")

    # Connectors
    if CONNECTORS_DIR.exists():
        for connector_path in CONNECTORS_DIR.iterdir():
            version_file = connector_path / "version.py"
            if not version_file.exists():
                continue
            version = read_version_file(version_file)
            connector_slug = connector_path.name.replace("_", "-") + "-connector"
            dest_dir = core_bundle / f"{connector_slug}-{version}"
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
            deploy_dir = connector_path / "deploy"
            # Copy compose files and env samples from deploy/docker if present
            docker_src_dir = deploy_dir / "docker"
            if docker_src_dir.exists():
                for f in docker_src_dir.glob("docker-compose-*.yaml"):
                    c.run(f"cp -f {f} {dest_dir}/{f.name}")
                for env_sample in docker_src_dir.glob("sample.*.env"):
                    c.run(f"cp -f {env_sample} {dest_dir}/{env_sample.name}")
            else:
                for f in deploy_dir.glob("docker-compose-*.yaml"):
                    c.run(f"cp -f {f} {dest_dir}/{f.name}")
            _append_bundle_readme(dest_dir / "README.md")
    # Tarball the whole bundle for convenience
    tarball = core_bundle.parent / f"dsx-connect-compose-bundle-{core_version}.tar.gz"
    if tarball.exists():
        tarball.unlink()
    c.run(f"cd {core_bundle.parent} && tar -czf {tarball.name} {core_bundle.name}")
    print(f"Copied bundle to {core_bundle}")
    print(f"Created archive {tarball}")


@task(pre=[generate_manifest])
def bundle_connector(c, name: str, zip_archive: bool = True):
    """
    Bundle a single connector's docker assets into docker_bundle/<connector>-bundle-<version>.
    e.g. `inv bundle-connector --name filesystem`
    """
    available = set(_configured_names(include_disabled=True))
    if name not in available:
        raise Exit(f"Unknown connector '{name}'. Valid options: {', '.join(sorted(available))}", code=2)

    connector_slug = name.replace("_", "-") + "-connector"
    version_file = CONNECTORS_DIR / name / "version.py"
    if not version_file.exists():
        raise Exit(f"No version.py found for connector '{name}'", code=2)
    version = read_version_file(version_file)
    deploy_dir = CONNECTORS_DIR / name / "deploy"

    def _copy_bundle_contents(dest_dir: Path):
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        docker_src = deploy_dir / "docker"
        if docker_src.exists():
            for f in docker_src.glob("*"):
                shutil.copy2(f, dest_dir / f.name)
        else:
            for compose in deploy_dir.glob("docker-compose-*.yaml"):
                shutil.copy2(compose, dest_dir / compose.name)
        _append_bundle_readme(dest_dir / "README.md")

    target_dir = PROJECT_ROOT / DEPLOYMENT_DIR / f"{connector_slug}-bundle-{version}"
    _clean_export_impl(str(target_dir))
    _copy_bundle_contents(target_dir)
    print(f"[bundle-connector] Bundle copied to {target_dir}")

    core_version = read_version_file(CORE_VERSION_FILE)
    versioned_core_dir = PROJECT_ROOT / DEPLOYMENT_DIR / f"dsx-connect-{core_version}"
    versioned_core_dir.mkdir(parents=True, exist_ok=True)
    nested_target = versioned_core_dir / f"{connector_slug}-{version}"
    _clean_export_impl(str(nested_target))
    _copy_bundle_contents(nested_target)
    print(f"[bundle-connector] Also copied bundle to {nested_target}")

    if zip_archive:
        _zip_export_impl(c, str(target_dir), str(target_dir.parent))
        print(f"[bundle-connector] Created archive {target_dir}.zip")


def _append_bundle_readme(path: Path):
    """
    Historically appended a Bundle Quickstart README; now a no-op.
    Clean up legacy quickstart content if present so bundles stay lean.
    """
    if not path.exists():
        return
    content = path.read_text()
    marker = "## Bundle Quickstart"
    if marker not in content:
        return
    # Remove the quickstart section and trim trailing whitespace; delete file if empty.
    before_marker = content.split(marker)[0].rstrip()
    if before_marker:
        path.write_text(before_marker + "\n")
    else:
        path.unlink()
