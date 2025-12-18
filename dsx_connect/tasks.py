"""
Invoke tasks for dsx-connect core.

Builds/pushes happen in-place (no staging/zip). Images are tagged with both the
version and :latest. Helm chart packaging/push is available via helm_* tasks.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
from invoke import task

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = PROJECT_ROOT.parent
IMAGE_NAME = "dsx-connect"
REPO_UNAME = "dsxconnect"
DEFAULT_HELM_REPO = "oci://registry-1.docker.io/dsxconnect"


def _read_version() -> str:
    content = (PROJECT_ROOT / "version.py").read_text()
    m = re.search(r"DSX_CONNECT_VERSION\s*=\s*[\"'](\d+\.\d+\.\d+)[\"']", content)
    if not m:
        raise ValueError("DSX_CONNECT_VERSION not found in version.py")
    return m.group(1)


def _update_chart_yaml(chart_path: pathlib.Path, version: str):
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


def _update_env_image_pin(env_path: pathlib.Path, image_repo: str, version: str):
    if not env_path.exists():
        return
    text = env_path.read_text()
    pattern = re.compile(rf"^(?P<prefix>\s*\w*IMAGE\s*=\s*{re.escape(image_repo)}:)(?P<tag>[^\s]+)", flags=re.MULTILINE)
    new_text, count = pattern.subn(rf"\g<prefix>{version}", text, count=1)
    if count:
        env_path.write_text(new_text)


@task
def bump(c):
    """Increment the patch version in dsx_connect/version.py."""
    filename = PROJECT_ROOT / "version.py"
    content = filename.read_text()
    pat = r'(DSX_CONNECT_VERSION\s*=\s*["\'])(\d+)\.(\d+)\.(\d+)(["\'])'
    m = re.search(pat, content)
    if not m:
        raise ValueError("Version string not found in version.py")
    major, minor, patch = int(m.group(2)), int(m.group(3)), int(m.group(4))
    new_version = f"{major}.{minor}.{patch + 1}"
    new_line = f"{m.group(1)}{new_version}{m.group(5)}"
    filename.write_text(re.sub(pat, new_line, content))
    print(f"Bumped version to {new_version}")
    env_sample = PROJECT_ROOT / "deploy" / "docker" / ".sample.core.env"
    _update_env_image_pin(env_sample, f"{REPO_UNAME}/{IMAGE_NAME}", new_version)


@task
def build(c):
    """Build the dsx-connect image (tags version and :latest)."""
    version = _read_version()
    version_tag = f"{IMAGE_NAME}:{version}"
    if c.run(f"docker images -q {version_tag}", hide=True).stdout.strip():
        print(f"Image {version_tag} already exists. Skipping build.")
        return

    dockerfile = PROJECT_ROOT / "Dockerfile"
    build_args = []
    for env_key, arg_key in (
        ("PY_BASE_IMAGE", "PY_BASE_IMAGE"),
        ("PIP_INDEX_URL", "PIP_INDEX_URL"),
        ("PIP_EXTRA_INDEX_URL", "PIP_EXTRA_INDEX_URL"),
    ):
        val = os.environ.get(env_key)
        if val:
            build_args += ["--build-arg", f"{arg_key}={val}"]
    ba = " ".join(build_args)
    print(f"Building image {version_tag} with {dockerfile} …")
    c.run(f"docker build {ba} -t {version_tag} -f {dockerfile} {REPO_ROOT}")
    c.run(f"docker tag {version_tag} {IMAGE_NAME}:latest")


@task(pre=[build])
def push(c, repo=REPO_UNAME):
    """Push versioned and latest tags."""
    version = _read_version()
    version_remote = f"{repo}/{IMAGE_NAME}:{version}"
    latest_remote = f"{repo}/{IMAGE_NAME}:latest"

    c.run(f"docker tag {IMAGE_NAME}:{version} {version_remote}")
    c.run(f"docker push {version_remote}")

    c.run(f"docker tag {IMAGE_NAME}:{version} {latest_remote}")
    c.run(f"docker push {latest_remote}")


@task
def helm_package(c, out_dir="dist/charts", version=None, app_version=None):
    """Package the Helm chart under dsx_connect/deploy/helm."""
    if version is None:
        version = _read_version()
    if app_version is None:
        app_version = version
    chart_dir = PROJECT_ROOT / "deploy" / "helm"
    _update_chart_yaml(chart_dir / "Chart.yaml", version)
    out_path = REPO_ROOT / out_dir
    out_path.mkdir(parents=True, exist_ok=True)

    charts_subdir = chart_dir / "charts"
    if charts_subdir.exists():
        for stale_dir in [charts_subdir / "syslog", charts_subdir / "dsx-collector-rsyslog"]:
            if stale_dir.exists():
                shutil.rmtree(stale_dir, ignore_errors=True)
        for f in charts_subdir.glob("*.tgz"):
            try:
                f.unlink()
            except Exception:
                pass

    build_res = c.run(f"helm dependency build {chart_dir}", warn=True, hide=True)
    build_out = (build_res.stdout or "") + (build_res.stderr or "")
    if build_res.exited != 0 or "lock file" in build_out and "out of sync" in build_out:
        print("[helm] Dependencies out of sync. Updating…")
        c.run(f"helm dependency update {chart_dir}")
        c.run(f"helm dependency build {chart_dir}")

    lint_res = c.run(f"helm lint {chart_dir}", warn=True, hide=True)
    if lint_res.exited != 0:
        if lint_res.stdout:
            print(lint_res.stdout)
        if lint_res.stderr:
            print(lint_res.stderr)
        raise SystemExit(lint_res.exited)

    c.run(
        f"helm package {chart_dir} --version {version} --app-version {app_version} --destination {out_path}"
    )
    print(f"[helm] Packaged chart to {out_path}")


@task
def helm_push(c, repo=DEFAULT_HELM_REPO, charts_dir="dist/charts", version=None):
    """Push packaged chart to an OCI repo."""
    if version is None:
        version = _read_version()
    chart_yaml = PROJECT_ROOT / "deploy" / "helm" / "Chart.yaml"
    m = re.search(r"^name:\s*([\w.-]+)", chart_yaml.read_text(), flags=re.MULTILINE)
    if not m:
        raise ValueError("Chart.yaml missing name")
    chart_name = m.group(1)
    tgz = (REPO_ROOT / charts_dir) / f"{chart_name}-{version}.tgz"
    if not tgz.exists():
        raise FileNotFoundError(f"Packaged chart not found: {tgz}. Run helm_package first.")
    res = c.run(f"helm push {tgz} {repo}", warn=True, hide=True)
    if res.exited != 0:
        out = (res.stdout or "") + (res.stderr or "")
        print(out)
        raise SystemExit(res.exited)
    print(f"[helm] Pushed {tgz} to {repo}")


@task
def helm_release(c, repo=DEFAULT_HELM_REPO, charts_dir="dist/charts"):
    """Package and push the Helm chart (no version bump)."""
    version = _read_version()
    helm_package(c, out_dir=charts_dir, version=version, app_version=version)
    helm_push(c, repo=repo, charts_dir=charts_dir, version=version)


@task(pre=[bump, build, push])
def release(c, helm_repo=DEFAULT_HELM_REPO):
    """Full release: bump → build → push → helm package/push."""
    version = _read_version()
    helm_package(c, version=version, app_version=version)
    helm_push(c, repo=helm_repo, version=version)
    try:
        c.run(f"git tag dsx-connect-{version}", warn=True)
    except Exception:
        pass


@task
def lint(c):
    """Run linters on the core."""
    c.run("flake8 app taskworkers database celery_app utils dsxa_client config.py endpoint_names.py")
    c.run("pylint app taskworkers database celery_app utils dsxa_client config.py endpoint_names.py")


@task
def test(c):
    """Run unit tests."""
    c.run("pytest tests app/tests taskworkers/tests database/tests celery_app/tests utils/tests dsxa_client/tests")
