import os
import uuid
import pytest
from pathlib import Path

try:
    # Load .dev.env early if integration is requested, to populate env vars
    from shared.dev_env import load_devenv
except Exception:
    load_devenv = None

try:
    import msal  # noqa: F401  # ensure msal is installed for live auth
    MSAL_AVAILABLE = True
except Exception:
    MSAL_AVAILABLE = False

from connectors.sharepoint.config import SharepointConnectorConfig
from connectors.sharepoint.sharepoint_client import SharePointClient


def _env(name: str) -> str | None:
    val = os.getenv(name)
    return val.strip() if val else None

def _env_alias(*names: str) -> str | None:
    """Return the first non-empty env var value among aliases."""
    for n in names:
        v = _env(n)
        if v:
            return v
    return None


RUN_INTEGRATION = (_env("RUN_SP_INTEGRATION") or "").lower() in {"1", "true", "yes"}

# Auto-load connectors/sharepoint/.dev.env if present and integration is enabled
if RUN_INTEGRATION and load_devenv is not None:
    try:
        dev_env_path = Path(__file__).resolve().parents[1] / ".dev.env"
        load_devenv(dev_env_path)
    except Exception:
        # Non-fatal: keep going; skip will trigger if envs missing
        pass
REQUIRED_ENVS = [
    "DSXCONNECTOR_SP_TENANT_ID",
    "DSXCONNECTOR_SP_CLIENT_ID",
    "DSXCONNECTOR_SP_CLIENT_SECRET",
    "DSXCONNECTOR_SP_HOSTNAME",
    "DSXCONNECTOR_SP_SITE_PATH",
]


def _missing_envs() -> list[str]:
    return [k for k in REQUIRED_ENVS if not _env(k)]


pytestmark = pytest.mark.skipif(
    not RUN_INTEGRATION or not MSAL_AVAILABLE or _missing_envs(),
    reason=(
        "SharePoint integration test skipped. Set RUN_SP_INTEGRATION=true and provide MSAL and required envs: "
        + ", ".join(REQUIRED_ENVS)
    ),
)


@pytest.mark.asyncio
async def test_sharepoint_live_roundtrip(tmp_path, capsys):
    """
    WARNING: This test can perform live operations against your SharePoint tenant.

    Modes (opt-in via env):
    - Read-only (default): downloads an existing file by ID/path or the first file in a folder.
      Provide SP_TEST_ITEM_ID or SP_TEST_ITEM_PATH, or SP_TEST_FOLDER to scan for a file.
    - Write mode (SP_TEST_ALLOW_CREATE=true): creates a small file under SP_TEST_FOLDER (default
      'dsxconnect-integration-tests/') and deletes it afterwards.

    Enable by setting RUN_SP_INTEGRATION=true and providing required env vars.
    """
    allow_create = (_env("SP_TEST_ALLOW_CREATE") or "").lower() in {"1", "true", "yes"}
    if allow_create:
        print(
            "[WARN] Running LIVE SharePoint integration test (WRITE MODE). It will create and delete a small file "
            "under the folder specified by SP_TEST_FOLDER (default 'dsxconnect-integration-tests/')."
        )
    else:
        print(
            "[WARN] Running LIVE SharePoint integration test (READ-ONLY MODE). It will download an existing file."
        )

    cfg = SharepointConnectorConfig(
        sp_tenant_id=_env("DSXCONNECTOR_SP_TENANT_ID"),
        sp_client_id=_env("DSXCONNECTOR_SP_CLIENT_ID"),
        sp_client_secret=_env("DSXCONNECTOR_SP_CLIENT_SECRET"),
        sp_hostname=_env("DSXCONNECTOR_SP_HOSTNAME"),
        sp_site_path=_env("DSXCONNECTOR_SP_SITE_PATH"),
        sp_drive_name=_env("DSXCONNECTOR_SP_DRIVE_NAME"),
        # Allow skipping TLS verification via env if needed for proxies; default True for Graph
        sp_verify_tls=(_env("DSXCONNECTOR_SP_VERIFY_TLS") or "true").lower() in {"1", "true", "yes"},
        sp_ca_bundle=_env("DSXCONNECTOR_SP_CA_BUNDLE"),
    )

    # Optional: log the raw access token and decoded claims for debugging when requested
    log_token = (_env_alias("SP_LOG_TOKEN", "DSXCONNECT_SP_LOG_TOKEN", "DSXCONNECTOR_SP_LOG_TOKEN") or "").lower() in {"1", "true", "yes"}
    if log_token:
        try:
            import msal, base64, json  # type: ignore
            def b64url_decode(s: str) -> bytes:
                s += '=' * (-len(s) % 4)
                return base64.urlsafe_b64decode(s.encode('utf-8'))
            app = msal.ConfidentialClientApplication(
                _env("DSXCONNECTOR_SP_CLIENT_ID"),
                authority=f"https://login.microsoftonline.com/{_env('DSXCONNECTOR_SP_TENANT_ID')}",
                client_credential=_env("DSXCONNECTOR_SP_CLIENT_SECRET"),
            )
            res = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
            token = res.get("access_token")
            if token:
                parts = token.split('.')
                header = json.loads(b64url_decode(parts[0]).decode('utf-8', 'ignore')) if len(parts) > 1 else {}
                claims = json.loads(b64url_decode(parts[1]).decode('utf-8', 'ignore')) if len(parts) > 1 else {}
                print("[TOKEN] access_token=", token)
                print("[TOKEN] header=", json.dumps(header, separators=(",", ":")))
                print("[TOKEN] claims=", json.dumps(claims, separators=(",", ":")))
            else:
                print("[TOKEN] Failed to acquire token:", res)
        except Exception as e:
            print("[TOKEN] Error acquiring or decoding token:", e)

    client = SharePointClient(cfg)

    if allow_create:
        test_folder = _env_alias("SP_TEST_FOLDER", "DSXCONNECT_SP_TEST_FOLDER", "DSXCONNECTOR_SP_TEST_FOLDER") or "dsxconnect-integration-tests"
        test_name = f"it-{uuid.uuid4().hex[:8]}.txt"
        test_path = f"{test_folder}/{test_name}"
        content = b"hello from integration test\n"

        # Ensure folder exists (skip if permissions are insufficient)
        try:
            folder_item = await client.ensure_folder(test_folder)
            assert folder_item and folder_item.get("id")
        except Exception as e:
            if "403" in str(e):
                pytest.skip("Insufficient permissions to create test folder (403). Run in read-only mode or adjust app permissions.")
            raise

        # Upload file
        try:
            uploaded = await client.upload_file(test_path, content)
        except Exception as e:
            if "403" in str(e):
                pytest.skip("Insufficient permissions to upload test file (403). Run in read-only mode or adjust app permissions.")
            raise
        assert uploaded and uploaded.get("id") and uploaded.get("name") == test_name
        item_id = uploaded["id"]

        # Download and verify
        resp = await client.download_file(item_id)
        assert resp.status_code == 200
        assert resp.content == content

        # Cleanup: delete (best-effort)
        try:
            await client.delete_file(item_id)
        except Exception:
            pass
    else:
        # Read-only flow: prefer explicit test item, otherwise list a folder and download the first file
        item_id = _env_alias("SP_TEST_ITEM_ID", "DSXCONNECT_SP_TEST_ITEM_ID", "DSXCONNECTOR_SP_TEST_ITEM_ID")
        item_path = _env_alias("SP_TEST_ITEM_PATH", "DSXCONNECT_SP_TEST_ITEM_PATH", "DSXCONNECTOR_SP_TEST_ITEM_PATH")
        folder = _env_alias("SP_TEST_FOLDER", "DSXCONNECT_SP_TEST_FOLDER", "DSXCONNECTOR_SP_TEST_FOLDER") or ""

        identifier = item_id or item_path
        if not identifier:
            # List a folder to find any file
            try:
                items = await client.list_files(folder)
            except Exception as e:
                pytest.skip(
                    f"Unable to list folder '{folder}': {e}. Provide SP_TEST_ITEM_PATH or SP_TEST_ITEM_ID, "
                    f"or adjust app permissions (Files.Read.All / Sites.Read.All)."
                )
            file = next((it for it in items if not it.get("folder")), None)
            if not file:
                pytest.skip("No files found to download in the specified folder; provide SP_TEST_ITEM_ID or SP_TEST_ITEM_PATH.")
            # Prefer stable item ID; if missing, construct a path within the drive using folder + filename
            if file.get("id"):
                identifier = file["id"]
            else:
                base = (folder or "").strip('/')
                name = file.get("name") or ""
                identifier = f"{base}/{name}" if base else name

        resp = await client.download_file(identifier)
        assert resp.status_code == 200
        # We cannot assume specific content; just assert non-empty
        assert resp.content is not None and len(resp.content) > 0

    # basic stdout capture to surface the warning in CI logs if ever enabled
    out = capsys.readouterr().out
    assert "[WARN] Running LIVE SharePoint integration test" in out
