"""
Use invoke to run this script.
pip install invoke
invoke <task>

ex: invoke release
"""
import os
import pathlib
import sys

from invoke import task

project_slug = "onedrive"
name = "onedrive-connector"
repo_uname = "dsxconnect"
DEFAULT_HELM_REPO = "oci://registry-1.docker.io/dsxconnect"

build_dir = "dist"
project_root_dir = str(pathlib.Path(__file__).resolve().parent.parent.parent)

sys.path.insert(0, project_root_dir)
from connectors.framework.tasks.common import (  # noqa: E402
    build_image,
    push_image,
    prepare_common_files,
    bump_patch_version,
    clean_export,
    zip_export,
    prepare_shared_files,
    read_connector_version,
    helm_package_connector,
    helm_push_oci_connector,
    update_env_sample_image,
)


def _current_version() -> str:
    return read_connector_version("version.py")


def _export_folder(version: str) -> str:
    return os.path.join(build_dir, f"{name}-{version}")


@task
def build(c):
    """Build the Docker image for the current version (in-place, no staging)."""
    version = _current_version()
    image_tag = f"{name}:{version}"
    dockerfile = pathlib.Path(project_root_dir) / "connectors" / project_slug / "Dockerfile"
    context = pathlib.Path(project_root_dir)
    if c.run(f"docker images -q {image_tag}", hide=True).stdout.strip():
        print(f"Image {image_tag} already exists. Skipping build.")
        return
    c.run(f"docker build -t {image_tag} -f {dockerfile} {context}")


@task(pre=[build])
def push(c):
    version = _current_version()
    push_image(c, repo=repo_uname, name=name, version=version)


@task
def release(c):
    """Bump version and perform full image + chart release (bump → build → push → helm_release)."""
    new_version = bump_patch_version("version.py")
    print(f"Bumped connector version to {new_version}")
    docker_env_dir = pathlib.Path(project_root_dir) / "connectors" / project_slug / "deploy" / "docker"
    for env_sample in docker_env_dir.glob(".sample*.env"):
        update_env_sample_image(env_sample, f"{repo_uname}/{name}", new_version)
    build(c)
    push(c)
    helm_release(c)
    try:
        c.run(f"git tag connector-{project_slug}-{new_version}", warn=True)
    except Exception:
        pass


@task
def helm_package(c, out_dir=None, version=None, app_version=None):
    if version is None:
        version = _current_version()
    if app_version is None:
        app_version = version
    if out_dir is None:
        out_dir = f"connectors/{project_slug}/{_export_folder(version)}"
    helm_package_connector(c, project_slug=project_slug, out_dir=out_dir, version=version, app_version=app_version)


@task
def helm_push_oci(c, repo=None, charts_dir=None, version=None):
    if version is None:
        version = _current_version()
    if repo is None:
        repo = os.environ.get("HELM_REPO", DEFAULT_HELM_REPO)
    if charts_dir is None:
        charts_dir = f"/tmp/{project_slug}-chart-{version}"
    helm_push_oci_connector(c, project_slug=project_slug, repo=repo, charts_dir=charts_dir, version=version)


@task
def helm_release(c, repo=None, out_dir=None, charts_dir=None, version=None, app_version=None):
    if version is None:
        version = _current_version()
    if app_version is None:
        app_version = version
    if repo is None:
        repo = os.environ.get("HELM_REPO", DEFAULT_HELM_REPO)
    if out_dir is None:
        out_dir = f"/tmp/{project_slug}-chart-{version}"
    if charts_dir is None:
        charts_dir = out_dir
    helm_package(c, out_dir=out_dir, version=version, app_version=app_version)
    helm_push_oci(c, repo=repo, charts_dir=charts_dir, version=version)


@task
def bump(c):
    """Bump the patch version in version.py (no build/push)."""
    new_version = bump_patch_version("version.py")
    print(f"Bumped connector version to {new_version}")
    return new_version
