import os
import re
import shutil
from pathlib import Path

from invoke import Context, task
import os


def bump_patch_version(version_file: str) -> str:
    """
    Increment the patch version in the given version.py file.

    Supports common constants used across this repo:
      - CONNECTOR_VERSION = "X.Y.Z"
      - DSX_CONNECT_VERSION = "X.Y.Z"
      - VERSION = "X.Y.Z"

    Returns the new version string.
    """
    path = Path(version_file)
    if not path.exists():
        raise FileNotFoundError(f"Version file not found: {version_file}")
    content = path.read_text()

    # Try the constants in priority order
    patterns = [
        r'(CONNECTOR_VERSION\s*=\s*["\'])(\d+)\.(\d+)\.(\d+)(["\'])',
        r'(DSX_CONNECT_VERSION\s*=\s*["\'])(\d+)\.(\d+)\.(\d+)(["\'])',
        r'(VERSION\s*=\s*["\'])(\d+)\.(\d+)\.(\d+)(["\'])',
    ]
    match = None
    pattern_used = None
    for pat in patterns:
        match = re.search(pat, content)
        if match:
            pattern_used = pat
            break
    if not match:
        raise ValueError(f"Version string not found in {version_file}")

    major = int(match.group(2))
    minor = int(match.group(3))
    patch = int(match.group(4))
    new_patch = patch + 1
    new_version = f"{major}.{minor}.{new_patch}"
    new_line = f"{match.group(1)}{new_version}{match.group(5)}"
    new_content = re.sub(pattern_used, new_line, content)
    path.write_text(new_content)
    return new_version


def clean_export(export_folder: str):
    """
    Remove existing distribution folder and its zip archive.
    """
    zip_file = f"{export_folder}.zip"
    print(f"Cleaning release folder: {export_folder} and {zip_file}...")
    if os.path.exists(export_folder):
        shutil.rmtree(export_folder)
    if os.path.exists(zip_file):
        os.remove(zip_file)


def prepare_shared_files(c: Context, project_root: str, export_folder: str):
    base = Path(export_folder)
    # Exclude dev certs from shared to avoid duplication; certs are copied to export/certs separately
    c.run(
        f"rsync -av --exclude='__pycache__' --exclude 'deploy/certs' {project_root}/shared {base}/"
    )
    (base / "__init__.py").touch()


def prepare_common_files(c: Context, project_slug: str, connector_name: str, version: str, project_root_dir: str,
                         export_folder: str):
    chart_file = Path(project_root_dir) / "connectors" / project_slug / "deploy" / "helm" / "Chart.yaml"
    _update_chart_yaml(chart_file, version)

    # Optionally generate dev certs once (shared across connectors)
    gen_flag = os.environ.get("GEN_DEV_CERTS", "").lower() in ("1", "true", "yes")
    if gen_flag:
        # Attempt to generate certs in shared first; fallback to connectors/framework
        for rel in ("shared/deploy/certs", "connectors/framework/deploy/certs"):
            try:
                cert_dir = Path(project_root_dir) / rel
                crt = cert_dir / "dev.localhost.crt"
                key = cert_dir / "dev.localhost.key"
                script = cert_dir / "generate-dev-cert.sh"
                if not crt.exists() or not key.exists():
                    if script.exists():
                        c.run(f"sh {script}", warn=True)
                # stop after first successful location
                if crt.exists() and key.exists():
                    break
            except Exception:
                pass
    #c.run(f"mkdir -p {export_folder}/connectors/azure_blob_storage")
    c.run(
        f"rsync -av --exclude '__pycache__' {project_root_dir}/connectors/{project_slug}/ {export_folder}/connectors/{project_slug}/ "
        f"--exclude 'deploy' --exclude 'dist' --exclude 'tasks.py' --exclude '.devenv' --exclude '.dev.env' --exclude '.env' "
        f"--exclude 'data/connector_uuid.txt'")
    c.run(
        f"rsync -av --exclude '__pycache__' {project_root_dir}/connectors/framework/ {export_folder}/connectors/framework/ --exclude 'tasks'")
    c.run(f"touch {export_folder}/connectors/__init__.py")

    # Bring root-level Dockerfile/requirements into export if present (for connectors that keep build files at root)
    root_dockerfile = Path(project_root_dir) / "connectors" / project_slug / "Dockerfile"
    if root_dockerfile.exists():
        shutil.copy2(root_dockerfile, Path(export_folder) / "Dockerfile")
    root_requirements = Path(project_root_dir) / "connectors" / project_slug / "requirements.txt"
    if root_requirements.exists():
        shutil.copy2(root_requirements, Path(export_folder) / "requirements.txt")

    # Also surface certs at export root for convenience/visibility (not required by Dockerfile)
    # Prefer shared certs; fallback to framework certs
    c.run(f"mkdir -p {export_folder}/certs && rsync -av {project_root_dir}/shared/deploy/certs/ {export_folder}/certs/ 2>/dev/null || true")
    c.run(f"mkdir -p {export_folder}/certs && rsync -av {project_root_dir}/connectors/framework/deploy/certs/ {export_folder}/certs/ 2>/dev/null || true")

    # Move deployment assets (compose, Docker build files, helm snippets) to export root
    # This preserves subfolders like deploy/docker and deploy/helm
    c.run(f"rsync -av {project_root_dir}/connectors/{project_slug}/deploy/ {export_folder}")

    # Backward/forward compatibility for Docker builds:
    # - If a connector uses deploy/docker/ for Dockerfile and requirements.txt,
    #   copy requirements.txt to export root so legacy Dockerfiles (COPY requirements.txt .)
    #   continue to work without editing every Dockerfile.
    try:
        req_src = Path(export_folder) / "docker" / "requirements.txt"
        req_dst = Path(export_folder) / "requirements.txt"
        if req_src.exists() and not req_dst.exists():
            shutil.copy2(req_src, req_dst)
    except Exception:
        pass

    # Ensure docker-compose YAMLs are available at export root as well
    try:
        docker_dir = Path(export_folder) / "docker"
        # Copy the canonical compose first if present
        primary = docker_dir / f"docker-compose-{connector_name}.yaml"
        to_copy: list[Path] = []
        if primary.exists():
            to_copy.append(primary)
        # Then copy any other docker-compose-*.yaml (e.g., -nfs variants)
        for f in docker_dir.glob("docker-compose-*.yaml"):
            if f not in to_copy:
                to_copy.append(f)
        for f in to_copy:
            dst = Path(export_folder) / f.name
            if not dst.exists():
                shutil.copy2(f, dst)
    except Exception:
        pass

    # copy start file to topmost directory
    c.run(f"rsync -av {project_root_dir}/connectors/{project_slug}/start.py {export_folder}/")

    # change the docker compose image: to reflect the new image tag
    file_path = Path(f"{export_folder}/docker-compose-{connector_name}.yaml")

    with file_path.open("r") as f:
        content = f.read()
        content = content.replace("__VERSION__", version)
    with file_path.open("w") as f:
        f.write(content)


def prepare_dsx_connect_files(c: Context, project_root: str, export_folder: str):
    # Deprecated: no longer copy dsx_connect into connector exports.
    return


def zip_export(c: Context, export_folder: str, build_dir: str):
    """
    Zip the contents of the export_folder into a .zip file alongside it.
    """
    zip_file = f"{export_folder}.zip"
    print(f"Zipping contents of {export_folder} into {zip_file}...")
    # Change directory to build_dir to ensure correct zip structure
    c.run(
        f"cd {build_dir} && zip -r {os.path.basename(zip_file)} {os.path.basename(export_folder)}"
    )


def build_image(c: Context, name: str, version: str, export_folder: str):
    image_tag = f"{name}:{version}"
    if c.run(f"docker images -q {image_tag}", hide=True).stdout.strip():
        print(f"Image {image_tag} already exists. Skipping build.")
        return

    # Prefer a Dockerfile under export/docker/, else fall back to export/Dockerfile
    dockerfile_path = Path(export_folder) / "docker" / "Dockerfile"
    if not dockerfile_path.exists():
        dockerfile_path = Path(export_folder) / "Dockerfile"

    print(f"Building docker image {image_tag} using {dockerfile_path} …")
    # Allow overriding base image and pip indexes via env -> build-args
    build_args = []
    for env_key, arg_key in (("PY_BASE_IMAGE", "PY_BASE_IMAGE"),
                             ("PIP_INDEX_URL", "PIP_INDEX_URL"),
                             ("PIP_EXTRA_INDEX_URL", "PIP_EXTRA_INDEX_URL")):
        val = os.environ.get(env_key)
        if val:
            build_args += ["--build-arg", f"{arg_key}={val}"]
    ba = " ".join(build_args)
    c.run(f"docker build {ba} -t {image_tag} -f {dockerfile_path} {export_folder}")


def push_image(c: Context, repo: str, name: str, version: str, push_latest: bool = True):
    """Push a versioned image and (optionally) also update/push :latest."""
    versioned_local = f"{name}:{version}"
    versioned_remote = f"{repo}/{name}:{version}"
    print(f"Pushing {versioned_remote}…")
    c.run(f"docker tag {versioned_local} {versioned_remote}")
    c.run(f"docker push {versioned_remote}")

    if push_latest:
        latest_local = f"{name}:latest"
        latest_remote = f"{repo}/{name}:latest"
        print(f"Tagging/pushing {latest_remote}…")
        c.run(f"docker tag {versioned_local} {latest_local}")
        c.run(f"docker tag {versioned_local} {latest_remote}")
        c.run(f"docker push {latest_remote}")


def update_env_sample_image(env_path: Path, image_repo: str, version: str):
    """Update an env sample file to pin the image tag to the given version."""
    if not env_path.exists():
        return
    text = env_path.read_text()
    pattern = re.compile(rf"^(?P<prefix>\s*\w*IMAGE\s*=\s*{re.escape(image_repo)}:)(?P<tag>[^\s]+)", flags=re.MULTILINE)
    new_text, count = pattern.subn(rf"\g<prefix>{version}", text, count=1)
    if count:
        env_path.write_text(new_text)


# -------------------- Version helpers --------------------
_CONNECTOR_VERSION_RE = re.compile(r"CONNECTOR_VERSION\s*=\s*[\"'](\d+\.\d+\.\d+)[\"']")


def _update_chart_yaml(chart_path: Path, version: str):
    if not chart_path.exists():
        return
    lines = chart_path.read_text().splitlines()
    app_present = False
    version_idx = None
    for idx, line in enumerate(lines):
        if line.startswith("version:"):
            lines[idx] = f"version: {version}"
            version_idx = idx
        elif line.startswith("appVersion:"):
            lines[idx] = f'appVersion: "{version}"'
            app_present = True
    if not app_present:
        insert_at = version_idx + 1 if version_idx is not None else len(lines)
        lines.insert(insert_at, f'appVersion: "{version}"')
    chart_path.write_text("\n".join(lines) + "\n")


def read_connector_version(version_file: str) -> str:
    path = Path(version_file)
    if not path.exists():
        raise FileNotFoundError(f"Version file not found: {version_file}")
    m = _CONNECTOR_VERSION_RE.search(path.read_text())
    if not m:
        raise ValueError(f"CONNECTOR_VERSION not found in {version_file}")
    return m.group(1)


def connector_image_name_from_slug(project_slug: str) -> str:
    return project_slug.replace("_", "-") + "-connector"


# -------------------- No-bump image release (for CI tags) --------------------
def release_connector_no_bump(c: Context, project_slug: str, repo_uname: str = "dsxconnect"):
    """
    Build and push a connector image without bumping CONNECTOR_VERSION.
    Assumes repo structure: connectors/<slug> with version.py and deploy/docker files.
    """
    root = Path(__file__).resolve().parents[3]  # repo root
    conn_dir = root / "connectors" / project_slug
    if not conn_dir.exists():
        raise FileNotFoundError(f"Connector dir not found: {conn_dir}")
    version = read_connector_version(str(conn_dir / "version.py"))
    name = connector_image_name_from_slug(project_slug)
    build_dir = root / "dist"
    export_folder = build_dir / f"{name}-{version}"

    print(f"[release:nobump] {project_slug} v{version}")
    clean_export(str(export_folder))
    prepare_shared_files(c, project_root=str(root), export_folder=str(export_folder))
    prepare_common_files(
        c,
        project_slug=project_slug,
        connector_name=name,
        version=version,
        project_root_dir=str(root),
        export_folder=str(export_folder),
    )
    zip_export(c, export_folder=str(export_folder), build_dir=str(build_dir))
    build_image(c, name=name, version=version, export_folder=str(export_folder))
    push_image(c, repo=repo_uname, name=name, version=version)


# -------------------- Helm packaging for connectors --------------------
def helm_package_connector(c: Context, project_slug: str, out_dir: str = "dist/charts",
                           version: str | None = None, app_version: str | None = None):
    """Package a connector Helm chart under connectors/<slug>/deploy/helm.

    - version/app_version default to CONNECTOR_VERSION.
    - Writes .tgz to out_dir.
    """
    root = Path(__file__).resolve().parents[3]
    chart_dir = root / "connectors" / project_slug / "deploy" / "helm"
    if not chart_dir.exists():
        raise FileNotFoundError(f"Chart dir not found: {chart_dir}")
    if version is None:
        version = read_connector_version(str(root / "connectors" / project_slug / "version.py"))
    if app_version is None:
        app_version = version
    chart_yaml = root / "connectors" / project_slug / "deploy" / "helm" / "Chart.yaml"
    _update_chart_yaml(chart_yaml, version)
    out_path = Path(out_dir)
    if not out_path.is_absolute():
        out_path = root / out_dir
    out_path.mkdir(parents=True, exist_ok=True)
    # Ensure lock is in sync first; auto-update when out of sync, then lint
    build_res = c.run(f"helm dependency build {chart_dir}", warn=True, hide=True)
    build_out = (build_res.stdout or "") + (build_res.stderr or "")
    if build_res.exited != 0 or "lock file" in build_out and "out of sync" in build_out:
        print(f"[helm] Dependencies out of sync for {project_slug}. Running: helm dependency update …")
        c.run(f"helm dependency update {chart_dir}")
        c.run(f"helm dependency build {chart_dir}")

    lint_res = c.run(f"helm lint {chart_dir}", warn=True, hide=True)
    if lint_res.exited != 0:
        out = (lint_res.stdout or "") + (lint_res.stderr or "")
        if "Chart.lock is out of sync with the dependencies file" in out or ("lock file" in out and "out of sync" in out):
            print(f"[helm] Dependencies out of sync for {project_slug}. Running: helm dependency update …")
            c.run(f"helm dependency update {chart_dir}")
            # Re-run lint after updating deps
            lint_res = c.run(f"helm lint {chart_dir}", warn=True, hide=True)
            out = (lint_res.stdout or "") + (lint_res.stderr or "")
            if lint_res.exited != 0:
                if lint_res.stdout:
                    print(lint_res.stdout)
                if lint_res.stderr:
                    print(lint_res.stderr)
                raise SystemExit(lint_res.exited)
        if lint_res.stdout:
            print(lint_res.stdout)
        if lint_res.stderr:
            print(lint_res.stderr)
        raise SystemExit(lint_res.exited)
    c.run(
        f"helm package {chart_dir} --version {version} --app-version {app_version} --destination {out_path}"
    )
    print(f"[helm] Packaged {project_slug} chart to {out_path}")


def helm_push_oci_connector(c: Context, project_slug: str, repo: str, charts_dir: str = "dist/charts",
                            version: str | None = None):
    """Push a connector chart .tgz to an OCI registry (e.g., oci://registry-1.docker.io/dsxconnect)."""
    root = Path(__file__).resolve().parents[3]
    if version is None:
        version = read_connector_version(str(root / "connectors" / project_slug / "version.py"))
    # The chart name comes from Chart.yaml 'name'. Read it to construct the packaged filename.
    chart_name_text = (root / "connectors" / project_slug / "deploy" / "helm" / "Chart.yaml").read_text()
    m = re.search(r"^name:\s*([\w.-]+)", chart_name_text, flags=re.MULTILINE)
    if not m:
        raise ValueError("Chart.yaml must have a 'name:' field")
    chart_name = m.group(1)
    charts_path = Path(charts_dir)
    if not charts_path.is_absolute():
        charts_path = root / charts_dir
    tgz = charts_path / f"{chart_name}-{version}.tgz"
    if not tgz.exists():
        raise FileNotFoundError(f"Packaged chart not found: {tgz}. Run helm package first.")
    res = c.run(f"helm push {tgz} {repo}", warn=True, hide=True)
    if res.exited != 0:
        out = (res.stdout or "") + (res.stderr or "")
        print(out)
        if "insufficient_scope" in out or "authorization failed" in out or "push access denied" in out:
            print("[helm] Push denied. Ensure you are logged in and the repo exists.")
            print("[helm] Try: helm registry login registry-1.docker.io -u <user> -p <token>")
            print(f"[helm] Or set HELM_REPO to a repo you can push: HELM_REPO={repo}")
        raise SystemExit(res.exited)
    print(f"[helm] Pushed {tgz} to {repo}")


# Optional: expose as invoke tasks (callable via -c path/to/module)
@task
def task_release_connector_nobump(c, name, repo_uname="dsxconnect"):
    release_connector_no_bump(c, project_slug=name, repo_uname=repo_uname)


@task
def task_helm_package_connector(c, name, out_dir="dist/charts"):
    helm_package_connector(c, project_slug=name, out_dir=out_dir)


@task
def task_helm_push_oci_connector(c, name, repo, charts_dir="dist/charts"):
    helm_push_oci_connector(c, project_slug=name, repo=repo, charts_dir=charts_dir)
