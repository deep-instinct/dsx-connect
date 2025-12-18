import os
import time
import signal
import subprocess
import random
import string
import json
from pathlib import Path
from invoke import task, Exit

try:
    import requests  # type: ignore
except Exception:
    requests = None

PROJECT_ROOT = Path(__file__).parent.resolve()


def _rand_token(n: int = 12) -> str:
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


@task
def test_auth(
    c,
    port: int = 8586,
    redis_url: str = "redis://localhost:6379/3",
    enroll_token: str = "",
    start_redis: bool = True,
):
    """
    Local smoke test for Enrollment + HMAC auth against a uvicorn dsx-connect API.

    - Starts Redis in Docker (optional, default True)
    - Launches uvicorn with auth enabled + enrollment token
    - Registers a dummy connector via X-Enrollment-Token and captures/reads HMAC creds
    - Calls a protected lightweight endpoint without HMAC (expects 401)
    - Calls the same endpoint with DSX-HMAC (expects 200)

    Usage:
      invoke -c test-tasks test-auth --port=8586 --redis-url=redis://localhost:6379/3
    """
    if requests is None:
        raise Exit("Python 'requests' package is required for test-auth. Please install it in your venv.")

    base = f"http://127.0.0.1:{port}"
    enroll_token = enroll_token or f"dev-{_rand_token(8)}"

    docker_cid = None
    uvicorn_proc: subprocess.Popen | None = None

    def _cleanup():
        try:
            if uvicorn_proc and uvicorn_proc.poll() is None:
                uvicorn_proc.send_signal(signal.SIGINT)
                try:
                    uvicorn_proc.wait(timeout=5)
                except Exception:
                    uvicorn_proc.kill()
        except Exception:
            pass
        if docker_cid:
            try:
                c.run(f"docker rm -f {docker_cid}", warn=True, hide=True)
            except Exception:
                pass

    try:
        # 1) Start Redis (if requested)
        if start_redis:
            print("[auth-test] Starting Redis container...")
            res = c.run("docker run -d -p 6379:6379 redis:7-alpine", hide=True, warn=True)
            if res.exited == 0:
                docker_cid = res.stdout.strip()
                print(f"[auth-test] Redis CID: {docker_cid}")
            else:
                print("[auth-test] Failed to start Redis container; assuming local Redis is available.")

        # 2) Launch uvicorn API
        print("[auth-test] Launching dsx-connect API (uvicorn)...")
        env = {
            **os.environ,
            "PYTHONPATH": str(PROJECT_ROOT),
            "DSXCONNECT_REDIS_URL": redis_url,
            "DSXCONNECT_RESULTS_DB": redis_url,
            "DSXCONNECT_AUTH__ENABLED": "true",
            "DSXCONNECT_AUTH__ENROLLMENT_TOKEN": enroll_token,
            "LOG_LEVEL": "debug",
        }
        uvicorn_proc = subprocess.Popen(
            [
                "python",
                "-m",
                "uvicorn",
                "dsx_connect.app.dsx_connect_api:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        # 3) Wait for health
        print("[auth-test] Waiting for API readiness...")
        deadline = time.time() + 30
        health = f"{base}/dsx-connect/api/v1/healthz"
        ready = False
        while time.time() < deadline:
            if uvicorn_proc.poll() is not None:
                _out = uvicorn_proc.stdout.read().decode() if uvicorn_proc.stdout else ""
                raise Exit(f"uvicorn exited early. Output:\n{_out}")
            try:
                r = requests.get(health, timeout=1.0)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ready:
            raise Exit("Timed out waiting for API readiness")
        print("[auth-test] API is up.")

        # 4) Register connector (Enrollment)
        reg_url = f"{base}/dsx-connect/api/v1/connectors/register"
        import uuid as _uuid
        payload = {
            "name": "test-connector",
            "uuid": str(_uuid.uuid4()),
            "url": f"http://localhost:9001/test-connector",
            "asset": "asset",
            "filter": "",
        }
        r = requests.post(reg_url, headers={"X-Enrollment-Token": enroll_token}, json=payload, timeout=5)
        if r.status_code not in (200, 201):
            raise Exit(f"Register failed: HTTP {r.status_code} => {r.text}")
        data = r.json()
        connector_uuid = data.get("connector_uuid") or payload["uuid"]
        hkid = data.get("hmac_key_id")
        hsec = data.get("hmac_secret")
        if not (hkid and hsec):
            try:
                import redis as _redis
                from dsx_connect.messaging.connector_keys import ConnectorKeys
                rcli = _redis.Redis.from_url(redis_url, decode_responses=True)
                hm = rcli.hgetall(ConnectorKeys.config(connector_uuid))
                hkid = hkid or hm.get("hmac_key_id")
                hsec = hsec or hm.get("hmac_secret")
            except Exception:
                pass
        if not (connector_uuid and hkid and hsec):
            raise Exit(f"Register did not return (or persist) HMAC creds: {data}")
        print(f"[auth-test] Registered connector {connector_uuid}; got HMAC kid={hkid}.")

        # 5) Protected endpoint without HMAC (expect 401). Use lightweight auth_check endpoint.
        protected = f"{base}/dsx-connect/api/v1/scan/auth_check"
        r = requests.post(protected, json={}, timeout=5)
        if r.status_code != 401:
            raise Exit(f"Expected 401 without HMAC, got {r.status_code}: {r.text}")
        print("[auth-test] Protected endpoint rejects unsigned requests (401) — OK.")

        # 6) Protected endpoint with HMAC (expect non-401, ideally 200)
        from shared.auth.hmac import make_hmac_header
        body = json.dumps({}).encode()
        path_q = "/dsx-connect/api/v1/scan/auth_check"
        hdr = make_hmac_header(hkid, hsec, "POST", path_q, body)
        r = requests.post(protected, data=body, headers={"Authorization": hdr, "Content-Type": "application/json"}, timeout=5)
        if r.status_code == 401:
            raise Exit(f"Expected non-401 with HMAC, got 401: {r.text}")
        print(f"[auth-test] Protected endpoint accepted signed request (HTTP {r.status_code}).")
        print("[auth-test] SUCCESS ✅")
    finally:
        _cleanup()


@task
def test_auth_connector(
    c,
    api_port: int = 8586,
    conn_port: int = 8590,
    redis_url: str = "redis://localhost:6379/3",
    enroll_token: str = "",
    start_redis: bool = True,
):
    """
    Local end-to-end auth smoke (API + filesystem connector).
    Usage:
      invoke -c test-tasks test-auth-connector
    """
    if requests is None:
        raise Exit("Python 'requests' package is required for test-auth-connector. Please install it.")

    api_base = f"http://127.0.0.1:{api_port}"
    enroll_token = enroll_token or f"dev-{_rand_token(8)}"

    docker_cid = None
    api_proc: subprocess.Popen | None = None
    conn_proc: subprocess.Popen | None = None

    def _cleanup():
        for p in [conn_proc, api_proc]:
            try:
                if p and p.poll() is None:
                    p.send_signal(signal.SIGINT)
                    try:
                        p.wait(timeout=5)
                    except Exception:
                        p.kill()
            except Exception:
                pass
        if docker_cid:
            try:
                c.run(f"docker rm -f {docker_cid}", warn=True, hide=True)
            except Exception:
                pass

    try:
        # 1) Redis
        if start_redis:
            print("[auth-conn] Starting Redis container...")
            res = c.run("docker run -d -p 6379:6379 redis:7-alpine", hide=True, warn=True)
            if res.exited == 0:
                docker_cid = res.stdout.strip()
                print(f"[auth-conn] Redis CID: {docker_cid}")
            else:
                print("[auth-conn] Failed to start Redis container; assuming local Redis available.")

        # 2) API (APP_ENV=prod so outbound HMAC is added)
        print("[auth-conn] Launching dsx-connect API (uvicorn)...")
        api_env = {
            **os.environ,
            "PYTHONPATH": str(PROJECT_ROOT),
            "DSXCONNECT_REDIS_URL": redis_url,
            "DSXCONNECT_RESULTS_DB": redis_url,
            "DSXCONNECT_AUTH__ENABLED": "true",
            "DSXCONNECT_AUTH__ENROLLMENT_TOKEN": enroll_token,
            "LOG_LEVEL": "debug",
        }
        api_proc = subprocess.Popen([
            "python", "-m", "uvicorn", "dsx_connect.app.dsx_connect_api:app",
            "--host", "0.0.0.0", "--port", str(api_port)
        ], cwd=str(PROJECT_ROOT), env=api_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        # Wait API
        health = f"{api_base}/dsx-connect/api/v1/healthz"
        deadline = time.time() + 30
        while time.time() < deadline:
            if api_proc.poll() is not None:
                out = api_proc.stdout.read().decode() if api_proc.stdout else ""
                raise Exit(f"API exited early. Output:\n{out}")
            try:
                r = requests.get(health, timeout=1.0)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise Exit("Timed out waiting for API readiness")
        print("[auth-conn] API ready.")

        # 3) Connector
        print("[auth-conn] Launching filesystem connector...")
        conn_env = {
            **os.environ,
            "PYTHONPATH": str(PROJECT_ROOT),
            "DSXCONNECT_ENROLLMENT_TOKEN": enroll_token,
            "DSXCONNECTOR_DSX_CONNECT_URL": api_base,
            "DSXCONNECTOR_CONNECTOR_URL": f"http://127.0.0.1:{conn_port}",
            "DSXCONNECTOR_AUTH__ENABLED": "true",
            "DSXCONNECTOR_USE_TLS": "false",
            "LOG_LEVEL": "debug",
        }
        conn_proc = subprocess.Popen([
            "python", "-m", "connectors.filesystem.start",
            "--host", "0.0.0.0", "--port", str(conn_port), "--workers", "1"
        ], cwd=str(PROJECT_ROOT), env=conn_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        # 4) Wait for connector to register (poll list)
        print("[auth-conn] Waiting for connector registration...")
        list_url = f"{api_base}/dsx-connect/api/v1/connectors/list"
        connector = None
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                r = requests.get(list_url, timeout=1.5)
                if r.status_code == 200:
                    arr = r.json() or []
                    for item in arr:
                        if item.get("name") == "filesystem-connector":
                            connector = item
                            break
                    if connector:
                        break
            except Exception:
                pass
            time.sleep(1.0)
        if not connector:
            out = conn_proc.stdout.read().decode() if conn_proc and conn_proc.stdout else ""
            raise Exit(f"Connector did not register in time. Logs:\n{out}")
        uuid = connector.get("uuid")
        print(f"[auth-conn] Connector registered: uuid={uuid}")

        # 5) Direct call to connector CONFIG without HMAC should 401
        try:
            direct = f"http://127.0.0.1:{conn_port}/filesystem-connector/config"
            r = requests.get(direct, timeout=2)
            if r.status_code != 401:
                raise Exit(f"Expected 401 from connector without HMAC, got {r.status_code}")
            print("[auth-conn] Connector rejects unsigned requests (401) — OK.")
        except requests.RequestException as e:
            raise Exit(f"Direct connector call failed unexpectedly: {e}")

        # 6) dsx-connect outbound HMAC check via new auth_check route
        authcheck_url = f"{api_base}/dsx-connect/api/v1/connectors/auth_check/{uuid}"
        r = requests.get(authcheck_url, timeout=5)
        if r.status_code == 401:
            raise Exit(f"Outbound HMAC rejected by connector: {r.text}")
        if r.status_code >= 500:
            raise Exit(f"Got server error via API: {r.status_code}: {r.text}")
        print(f"[auth-conn] dsx-connect → connector HMAC auth_check succeeded (HTTP {r.status_code}).")
        print("[auth-conn] SUCCESS ✅")
    finally:
        _cleanup()


# ---------------------- Pytest convenience tasks ---------------------- #


def _run_pytest(c, target: str):
    """Helper to run pytest against a specific target path."""
    cmd = f"cd {PROJECT_ROOT} && pytest {target}"
    c.run(cmd)


@task
def test_unit_auth_jwt(c):
    """Run unit tests covering JWT auth helpers."""
    _run_pytest(c, "tests/test_auth_jwt.py")


@task
def test_unit_client_hmac(c):
    """Run tests for outbound connector client param + HMAC handling."""
    _run_pytest(c, "tests/test_client_hmac_and_params.py")


@task
def test_unit_full_scan_limit(c):
    """Validate full_scan forwarding of limit parameters."""
    _run_pytest(c, "tests/test_connectors_full_scan_limit.py")


@task
def test_unit_repo_check_preview(c):
    """Validate repo_check forwarding of preview parameters."""
    _run_pytest(c, "tests/test_connectors_repo_check_preview.py")


@task
def test_unit_devenv(c):
    """Run tests for shared.dev_env helpers."""
    _run_pytest(c, "tests/test_devenv.py")


@task
def test_unit_hmac_shared(c):
    """Run shared.auth.hmac round-trip tests."""
    _run_pytest(c, "tests/test_hmac_shared.py")
