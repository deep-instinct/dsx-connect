from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dsx_connect_ng.app import create_app
from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.models import ConnectorInstanceRegister, IntegrationCreate, ProtectedScopeCreate
from dsx_connect_ng.jobs.models import BatchJobSubmitRequest, StageUpdateRequest


@pytest.fixture(autouse=True)
def force_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "control_plane_backend", "memory")
    monkeypatch.setattr(settings, "job_bus_backend", "memory")


def test_operator_console_page_renders() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/ui/")

    assert response.status_code == 200
    assert "DSX-Connect Operator Console" in response.text
    assert "DSX-Connect v2.0.0 Operator Console" not in response.text
    assert "Add Repository Connector" in response.text
    assert "Preconfigure a repository boundary before a runtime instance registers." in response.text
    assert 'id="connectors-table"' in response.text
    assert "function renderDataTable" in response.text
    assert 'href="/api/v1/ui-static/icons/dsx-connect-icon-squircle.svg"' in response.text
    assert 'src="/api/v1/ui-static/icons/dsx-connect-icon-squircle.svg"' in response.text
    assert 'href="/api/v1/ui-static/manifest.webmanifest"' in response.text
    assert 'class="rail-item" type="button" data-tab="assets"' in response.text
    assert 'id="connector-drawer"' in response.text
    assert "Protection Profile Editor" in response.text
    assert "Default Protection Profile" in response.text
    assert 'id="create-policy"' in response.text
    assert 'id="policy-editor-drawer"' in response.text
    assert 'id="policy-editor-save"' in response.text
    assert 'id="policy-editor-cancel"' in response.text
    assert "Malicious verdicts" in response.text
    assert "Detect Only" in response.text
    assert "Quarantine Folder Path" in response.text
    assert '<option value="operations">Operations</option>' in response.text
    assert '<option value="security">Security Console</option>' in response.text
    assert 'id="stat-dsxa"' in response.text
    assert 'dsxaStatus: "/api/v1/ui/dsxa/status"' in response.text


def test_operator_console_serves_icon_assets() -> None:
    client = TestClient(create_app())

    svg_response = client.get("/api/v1/ui-static/icons/dsx-connect-icon-squircle.svg")
    png_response = client.get("/api/v1/ui-static/icons/dsx-connect-icon-squircle-32.png")
    manifest_response = client.get("/api/v1/ui-static/manifest.webmanifest")

    assert svg_response.status_code == 200
    assert "image/svg+xml" in svg_response.headers["content-type"]
    assert "<svg" in svg_response.text
    assert png_response.status_code == 200
    assert png_response.headers["content-type"] == "image/png"
    assert manifest_response.status_code == 200
    assert manifest_response.json()["short_name"] == "DSX-Connect"


def test_ui_meta_returns_display_version() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/ui/meta")

    assert response.status_code == 200
    assert response.json() == {
        "product": "DSX-Connect",
        "version": "2.0.1",
        "display_name": "DSX-Connect v2.0.1",
    }


def test_ui_dsxa_status_reports_stub(monkeypatch) -> None:
    monkeypatch.setattr(settings.scanner, "mode", "stub")
    monkeypatch.setattr(settings.scanner, "base_url", "")
    client = TestClient(create_app())

    response = client.get("/api/v1/ui/dsxa/status")

    assert response.status_code == 200
    assert response.json()["state"] == "stub"
    assert response.json()["label"] == "DSXA stub"


def test_ui_dsxa_status_reports_unreachable(monkeypatch) -> None:
    from urllib import error as urllib_error

    from dsx_connect_ng.api.routes import ui as ui_routes

    def fail_urlopen(*args, **kwargs):
        raise urllib_error.URLError("connection refused")

    monkeypatch.setattr(settings.scanner, "mode", "dsxa")
    monkeypatch.setattr(settings.scanner, "base_url", "http://scanner.local:15000")
    monkeypatch.setattr(ui_routes.urllib_request, "urlopen", fail_urlopen)
    client = TestClient(create_app())

    response = client.get("/api/v1/ui/dsxa/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "unreachable"
    assert payload["label"] == "DSXA can't reach"
    assert payload["endpoint"] == "http://scanner.local:15000/"


def test_ui_dsxa_status_reports_scheme_mismatch_when_http_answers(monkeypatch) -> None:
    from urllib import error as urllib_error

    from dsx_connect_ng.api.routes import ui as ui_routes

    class Response:
        status = 404

        def __enter__(self):
            raise urllib_error.HTTPError(
                url="http://scanner.local:15000/",
                code=404,
                msg="not found",
                hdrs=None,
                fp=None,
            )

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(request, *args, **kwargs):
        if request.full_url.startswith("https://"):
            raise urllib_error.URLError("_ssl.c:983: The handshake operation timed out")
        return Response()

    monkeypatch.setattr(settings.scanner, "mode", "dsxa")
    monkeypatch.setattr(settings.scanner, "base_url", "https://scanner.local:15000")
    monkeypatch.setattr(settings.scanner, "verify_tls", False)
    monkeypatch.setattr(ui_routes.urllib_request, "urlopen", fake_urlopen)
    client = TestClient(create_app())

    response = client.get("/api/v1/ui/dsxa/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "scheme_mismatch"
    assert payload["label"] == "DSXA use HTTP"
    assert payload["endpoint"] == "http://scanner.local:15000/"
    assert payload["details"]["configured_endpoint"] == "https://scanner.local:15000/"


def test_ui_integrations_summary_includes_scope_counts_and_health(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    service.create_integration(
        IntegrationCreate(
            integration_id="gcs-a",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            capability_remediate=True,
            config={
                "reader": {
                    "default_strategy": "proxy",
                    "proxy": {
                        "base_url": "http://127.0.0.1:8630",
                        "connector_name": "google-cloud-storage-connector",
                    },
                },
                "remediation": {
                    "supports_move": True,
                    "supports_tag": True,
                    "supports_movetag": True,
                },
            },
        )
    )
    service.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="gcs-a",
            scope_type="path",
            resource_selector="bucket-a/prefix",
            display_name="Bucket A",
            mode="full_scan",
        )
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    monkeypatch.setattr(
        ui_routes,
        "_probe_connector_health",
        lambda base_url, connector_name: ui_routes.ConnectorHealthStatus(
            status="healthy",
            endpoint=f"{base_url}/{connector_name}/healthz",
            details={"ok": True},
        ),
    )

    client = TestClient(app)
    response = client.get("/api/v1/ui/integrations")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["integration"]["integration_id"] == "gcs-a"
    assert payload[0]["scope_count"] == 1
    assert payload[0]["health"]["status"] == "healthy"
    assert payload[0]["proxy_base_url"] == "http://127.0.0.1:8630"
    assert payload[0]["connector_name"] == "google-cloud-storage-connector"


def test_ui_integrations_summary_prefers_registered_connector_health() -> None:
    app = create_app()
    service = app.state.control_plane_service
    connector = service.register_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="gcs-pod-1",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            connector_name="google-cloud-storage-connector",
            connector_version="0.5.55",
            base_url="http://gcs:80",
            capabilities={"discover": True, "read": True, "write": True},
            health="healthy",
            labels={"namespace": "dsx-connect"},
        )
    )
    service.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id=connector.integration_id,
            scope_type="path",
            resource_selector="bucket-a/prefix",
            display_name="Bucket A",
            mode="full_scan",
        )
    )

    client = TestClient(app)
    response = client.get("/api/v1/ui/integrations")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["connector_instance_count"] == 1
    assert payload[0]["connector_instances"][0]["connector_instance_id"] == "gcs-pod-1"
    assert payload[0]["health"]["status"] == "healthy"
    assert payload[0]["health"]["endpoint"] == "http://gcs:80"
    assert payload[0]["health"]["details"]["connector_instance_id"] == "gcs-pod-1"


def test_ui_assets_connectors_returns_tab_aligned_connector_summary(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    service.create_integration(
        IntegrationCreate(
            integration_id="fs-a",
            platform="filesystem",
            platform_key="local",
            display_name="Filesystem A",
            config={},
        )
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    monkeypatch.setattr(
        ui_routes,
        "_probe_connector_health",
        lambda base_url, connector_name: ui_routes.ConnectorHealthStatus(status="unknown", details={"reason": "test"}),
    )

    client = TestClient(app)
    response = client.get("/api/v1/ui/assets/connectors")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["connectors"]) == 1
    assert payload["connectors"][0]["integration"]["integration_id"] == "fs-a"
    assert payload["connectors"][0]["integration"]["platform"] == "filesystem"


def test_ui_overview_returns_integrations_scopes_and_jobs(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    service.create_integration(
        IntegrationCreate(
            integration_id="fs-a",
            platform="filesystem",
            platform_key="local-fs",
            display_name="Filesystem A",
            config={},
        )
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    monkeypatch.setattr(
        ui_routes,
        "_probe_connector_health",
        lambda base_url, connector_name: ui_routes.ConnectorHealthStatus(status="unknown", details={"reason": "test"}),
    )

    client = TestClient(app)
    response = client.get("/api/v1/ui/overview")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["integrations"]) == 1
    assert payload["integrations"][0]["integration"]["integration_id"] == "fs-a"
    assert payload["scopes"] == []
    assert payload["jobs"] == []


def test_ui_scope_scan_submits_batch_for_scope_selector(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    service.create_integration(
        IntegrationCreate(
            integration_id="gcs-a",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            config={},
        )
    )
    service.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="gcs-a",
            scope_type="path",
            resource_selector="BadMojoResume",
            display_name="Bad Mojo",
            mode="full_scan",
        )
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    monkeypatch.setattr(
        ui_routes,
        "_probe_connector_health",
        lambda base_url, connector_name: ui_routes.ConnectorHealthStatus(status="unknown", details={"reason": "test"}),
    )

    client = TestClient(app)
    response = client.post("/api/v1/ui/scopes/scope-a/scan", json={"reader_strategy": "proxy"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["integration_id"] == "gcs-a"
    assert payload["job"]["scope_id"] == "scope-a"
    assert payload["job"]["payload"]["source"] == "ui_scope_scan"
    assert payload["job"]["payload"]["enumerationMode"] == "selector_only"
    assert payload["item_summary"]["total"] == 1

    job_id = payload["job"]["job_id"]
    items = client.get(f"/api/v1/execution/jobs/{job_id}/items").json()
    assert items[0]["object_identity"] == "BadMojoResume"
    assert items[0]["payload"]["readerStrategy"] == "proxy"
    assert items[0]["payload"]["path"] == "BadMojoResume"

    progress = client.get(f"/api/v1/execution/jobs/{job_id}/progress").json()
    assert progress["job_id"] == job_id
    assert progress["total_items"] == 1
    assert progress["item_summary"]["total"] == 1
    assert progress["backlog"]["queued"] == 1
    assert progress["derived_from_item_count"] == 1


def test_ui_scope_scan_uses_connector_preview_items(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    service.create_integration(
        IntegrationCreate(
            integration_id="gcs-a",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            config={
                "reader": {
                    "default_strategy": "proxy",
                    "proxy": {
                        "base_url": "http://127.0.0.1:8630",
                        "connector_name": "google-cloud-storage-connector",
                    },
                },
            },
        )
    )
    service.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="gcs-a",
            scope_type="path",
            resource_selector="bucket-a",
            display_name="Bucket A",
            mode="full_scan",
        )
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    monkeypatch.setattr(
        ui_routes,
        "_fetch_connector_preview",
        lambda base_url, connector_name, *, limit: ["bucket-a/eicar.com", "bucket-a/clean.txt"],
    )

    client = TestClient(app)
    response = client.post("/api/v1/ui/scopes/scope-a/scan", json={"reader_strategy": "proxy", "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["payload"]["enumerationMode"] == "connector_preview"
    assert payload["job"]["payload"]["itemCount"] == 2
    assert payload["item_summary"]["total"] == 2

    job_id = payload["job"]["job_id"]
    items = client.get(f"/api/v1/execution/jobs/{job_id}/items").json()
    assert [item["object_identity"] for item in items] == ["bucket-a/eicar.com", "bucket-a/clean.txt"]
    assert [item["payload"]["path"] for item in items] == ["eicar.com", "clean.txt"]


def test_ui_scope_scan_uses_connector_object_listing(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    service.create_integration(
        IntegrationCreate(
            integration_id="gcs-a",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            config={
                "reader": {
                    "default_strategy": "proxy",
                    "proxy": {
                        "base_url": "http://127.0.0.1:8630",
                        "connector_name": "google-cloud-storage-connector",
                    },
                },
            },
        )
    )
    service.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="gcs-a",
            scope_type="path",
            resource_selector="bucket-a",
            display_name="Bucket A",
            mode="full_scan",
        )
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    monkeypatch.setattr(
        ui_routes,
        "_fetch_connector_object_listing",
        lambda base_url, connector_name, *, scope, max_items: (
            [
                {"identity": "bucket-a/one.pdf", "location": "one.pdf", "size_in_bytes": 123},
                {"identity": "bucket-a/nested/two.docx", "location": "nested/two.docx"},
            ],
            True,
            2,
        ),
    )

    client = TestClient(app)
    response = client.post("/api/v1/ui/scopes/scope-a/scan", json={"reader_strategy": "proxy", "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["payload"]["enumerationMode"] == "connector_object_listing"
    assert payload["job"]["payload"]["enumerationPages"] == 2
    assert payload["job"]["payload"]["itemCount"] == 2

    job_id = payload["job"]["job_id"]
    items = client.get(f"/api/v1/execution/jobs/{job_id}/items").json()
    assert [item["object_identity"] for item in items] == ["bucket-a/one.pdf", "bucket-a/nested/two.docx"]
    assert [item["payload"]["path"] for item in items] == ["one.pdf", "nested/two.docx"]
    assert items[0]["payload"]["sizeInBytes"] == 123


def test_ui_asset_discovery_reconciles_protected_scopes(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    service.create_integration(
        IntegrationCreate(
            integration_id="gcs-a",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            config={
                "reader": {
                    "default_strategy": "proxy",
                    "proxy": {
                        "base_url": "http://127.0.0.1:8630",
                        "connector_name": "google-cloud-storage-connector",
                    },
                },
            },
        )
    )
    service.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="gcs-a",
            scope_type="path",
            resource_selector="bucket-a",
            display_name="Bucket A",
            mode="full_scan",
        )
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    def fake_fetch_assets(
        base_url,
        connector_name,
        *,
        asset_type,
        source,
        limit,
        cursor,
        asset_filter_mode=None,
        asset_filter_value=None,
    ):
        return {
            "asset_type": "bucket",
            "source": source,
            "status": "success",
            "assets": [
                {"id": "bucket-a", "display_name": "Bucket A", "selector": "bucket-a", "metadata": {"provider": "gcs"}},
                {"id": "bucket-b", "display_name": "Bucket B", "selector": "bucket-b", "metadata": {"provider": "gcs"}},
            ],
            "next_cursor": None,
        }

    monkeypatch.setattr(ui_routes, "_fetch_connector_assets", fake_fetch_assets)

    client = TestClient(app)
    response = client.get("/api/v1/ui/integrations/gcs-a/assets?type=bucket&source=inventory_enumeration")

    assert response.status_code == 200
    payload = response.json()
    assert payload["integration_id"] == "gcs-a"
    assert payload["asset_type"] == "bucket"
    assert payload["source"] == "inventory_enumeration"
    assert payload["status"] == "success"
    assert payload["assets"][0]["selector"] == "bucket-a"
    assert payload["assets"][0]["coverage_state"] == "protected"
    assert payload["assets"][0]["matching_scope_id"] == "scope-a"
    assert payload["assets"][1]["selector"] == "bucket-b"
    assert payload["assets"][1]["coverage_state"] == "unprotected"


def test_ui_assets_protected_aggregates_discovered_assets_with_policy(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    service.create_integration(
        IntegrationCreate(
            integration_id="gcs-a",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            config={
                "reader": {
                    "default_strategy": "proxy",
                    "proxy": {
                        "base_url": "http://127.0.0.1:8630",
                        "connector_name": "google-cloud-storage-connector",
                    },
                },
            },
        )
    )
    service.create_integration(
        IntegrationCreate(
            integration_id="fs-a",
            platform="filesystem",
            platform_key="local",
            display_name="Filesystem A",
            config={},
        )
    )
    service.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="gcs-a",
            scope_type="path",
            resource_selector="bucket-a",
            display_name="Bucket A",
            mode="full_scan",
            post_scan_policy={"malicious": "quarantine"},
        )
    )
    job_service = app.state.job_service
    batch = asyncio.run(
        job_service.submit_batch_job(
            BatchJobSubmitRequest(
                job_id="job-asset-last-scan",
                integration_id="gcs-a",
                scope_id="scope-a",
                payload={"source": "ui_scope_scan", "scopeSelector": "bucket-a"},
                items=[
                    {"object_identity": "bucket-a/clean.pdf"},
                    {"object_identity": "bucket-a/malware.exe"},
                ],
            )
        )
    )
    clean, malicious = job_service.list_job_items(job_id=batch.job.job_id, limit=10)
    job_service.complete_scan_only(
        clean.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-clean"}),
    )
    job_service.complete_scan_only(
        malicious.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Malicious", "scanGuid": "scan-malicious"}),
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    def fake_fetch(
        base_url,
        connector_name,
        *,
        asset_type,
        source,
        limit,
        cursor,
        asset_filter_mode=None,
        asset_filter_value=None,
    ):
        assert asset_type == "bucket"
        return {
            "asset_type": "bucket",
            "source": source,
            "status": "success",
            "assets": [
                {"id": "bucket-a", "display_name": "Bucket A", "selector": "bucket-a"},
                {"id": "bucket-b", "display_name": "Bucket B", "selector": "bucket-b"},
            ],
            "next_cursor": "next-page",
        }

    monkeypatch.setattr(ui_routes, "_fetch_connector_assets", fake_fetch)

    client = TestClient(app)
    response = client.get("/api/v1/ui/assets/protected?connector_type=gcs&type=bucket&source=inventory_enumeration")

    assert response.status_code == 200
    payload = response.json()
    assert payload["unsupported_integrations"] == []
    assert payload["failed_integrations"] == []
    assert payload["next_cursors"] == {"gcs-a": "next-page"}
    assert [asset["selector"] for asset in payload["assets"]] == ["bucket-a", "bucket-b"]
    assert payload["assets"][0]["integration_id"] == "gcs-a"
    assert payload["assets"][0]["platform"] == "gcs"
    assert payload["assets"][0]["coverage_state"] == "protected"
    assert payload["assets"][0]["matching_scope_id"] == "scope-a"
    assert payload["assets"][0]["policy"] == {"malicious": "quarantine"}
    assert payload["assets"][0]["last_scan"]["job_id"] == "job-asset-last-scan"
    assert payload["assets"][0]["last_scan"]["state"] == "completed"
    assert payload["assets"][0]["last_scan"]["terminal_items"] == 2
    assert payload["assets"][0]["findings"]["clean"] == 1
    assert payload["assets"][0]["findings"]["malicious"] == 1
    assert payload["assets"][1]["coverage_state"] == "unprotected"
    assert payload["assets"][1]["policy"] == {}
    assert payload["assets"][1]["last_scan"] is None
    assert payload["assets"][1]["findings"] == {}

    protected_only = client.get("/api/v1/ui/assets/protected?connector_type=gcs&type=bucket&coverage_state=protected")
    assert protected_only.status_code == 200
    assert [asset["selector"] for asset in protected_only.json()["assets"]] == ["bucket-a"]


def test_ui_assets_protected_uses_registered_connector_instance_endpoint(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    connector = service.register_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="gcs-pod-1",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            connector_name="google-cloud-storage-connector",
            base_url="http://gcs/google-cloud-storage-connector",
            capabilities={"discover": True, "read": True},
            health="healthy",
        )
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    def fake_fetch(
        base_url,
        connector_name,
        *,
        asset_type,
        source,
        limit,
        cursor,
        asset_filter_mode=None,
        asset_filter_value=None,
    ):
        assert base_url == "http://gcs/google-cloud-storage-connector"
        assert connector_name is None
        assert limit == 250
        return {
            "asset_type": asset_type,
            "source": source,
            "status": "success",
            "assets": [{"id": "bucket-a", "display_name": "Bucket A", "selector": "bucket-a"}],
        }

    monkeypatch.setattr(ui_routes, "_fetch_connector_assets", fake_fetch)

    client = TestClient(app)
    response = client.get(
        f"/api/v1/ui/assets/protected?integration_id={connector.integration_id}&type=bucket&source=inventory_enumeration&limit=250"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assets"][0]["selector"] == "bucket-a"
    assert payload["assets"][0]["coverage_state"] == "unprotected"


def test_ui_assets_protected_forwards_paging_and_asset_filter(monkeypatch) -> None:
    app = create_app()
    service = app.state.control_plane_service
    connector = service.register_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="gcs-pod-1",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            connector_name="google-cloud-storage-connector",
            base_url="http://gcs/google-cloud-storage-connector",
            capabilities={"discover": True, "read": True},
            health="healthy",
        )
    )

    from dsx_connect_ng.api.routes import ui as ui_routes

    def fake_fetch(
        base_url,
        connector_name,
        *,
        asset_type,
        source,
        limit,
        cursor,
        asset_filter_mode=None,
        asset_filter_value=None,
    ):
        assert limit == 15
        assert cursor == "page-2"
        assert asset_filter_mode == "begins_with"
        assert asset_filter_value == "prod"
        return {
            "asset_type": asset_type,
            "source": source,
            "status": "success",
            "assets": [
                {"id": "prod-a", "display_name": "prod-a", "selector": "prod-a"},
                {"id": "dev-a", "display_name": "dev-a", "selector": "dev-a"},
            ],
            "next_cursor": "page-3",
        }

    monkeypatch.setattr(ui_routes, "_fetch_connector_assets", fake_fetch)

    client = TestClient(app)
    response = client.get(
        f"/api/v1/ui/assets/protected?integration_id={connector.integration_id}"
        "&type=bucket&source=inventory_enumeration&limit=15&cursor=page-2"
        "&asset_filter_mode=begins_with&asset_filter_value=prod"
    )

    assert response.status_code == 200
    payload = response.json()
    assert [asset["selector"] for asset in payload["assets"]] == ["prod-a"]
    assert payload["next_cursors"] == {connector.integration_id: "page-3"}


def test_ui_scan_results_returns_operator_summary() -> None:
    app = create_app()
    control_plane = app.state.control_plane_service
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="gcs-a",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            config={},
        )
    )
    control_plane.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="gcs-a",
            scope_type="path",
            resource_selector="bucket-a",
            display_name="Bucket A",
            mode="full_scan",
        )
    )
    job_service = app.state.job_service
    batch = asyncio.run(
        job_service.submit_batch_job(
            BatchJobSubmitRequest(
                job_id="job-ui-results",
                integration_id="gcs-a",
                scope_id="scope-a",
                payload={"source": "ui_scope_scan", "scopeSelector": "bucket-a"},
                items=[
                    {"object_identity": "bucket-a/clean.pdf"},
                    {"object_identity": "bucket-a/malware.exe"},
                    {"object_identity": "bucket-a/pending.docx"},
                ],
            )
        )
    )
    items = job_service.list_job_items(job_id=batch.job.job_id, limit=10)
    clean, malicious, _pending = items
    job_service.complete_scan_only(
        clean.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-clean"}),
    )
    job_service.complete_scan_only(
        malicious.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Malicious", "scanGuid": "scan-malicious"}),
    )
    job_service.update_remediation_stage(
        malicious.job_item_id,
        StageUpdateRequest(state="completed", result={"action": "quarantine", "outcome": "success"}),
    )

    client = TestClient(app)
    response = client.get("/api/v1/ui/scan-results?integration_id=gcs-a&item_limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 1
    result = payload["results"][0]
    assert result["job"]["job_id"] == "job-ui-results"
    assert result["target"]["integration_id"] == "gcs-a"
    assert result["target"]["scope_id"] == "scope-a"
    assert result["target"]["source"] == "ui_scope_scan"
    assert result["target"]["label"] == "bucket-a"
    assert result["progress"]["total_items"] == 3
    assert result["progress"]["terminal_items"] == 2
    assert result["progress"]["completed_items"] == 2
    assert result["findings"]["clean"] == 1
    assert result["findings"]["malicious"] == 1
    assert result["findings"]["unknown"] == 1
    assert result["findings"]["sampled_items"] == 3
    assert result["remediation"]["completed"] == 1
    assert result["cancel"]["mode"] == "cooperative"
    assert result["cancel"]["immediate_file_level_cancel"] is False
    assert "in-memory scan batch" in result["cancel"]["message"]


def test_ui_scan_results_state_filter() -> None:
    app = create_app()
    control_plane = app.state.control_plane_service
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="fs-a",
            platform="filesystem",
            platform_key="local",
            display_name="Filesystem A",
            config={},
        )
    )
    job_service = app.state.job_service
    asyncio.run(
        job_service.submit_batch_job(
            BatchJobSubmitRequest(
                job_id="job-visible",
                integration_id="fs-a",
                items=[{"object_identity": "/tmp/a.txt"}],
            )
        )
    )
    cancelled = asyncio.run(
        job_service.submit_batch_job(
            BatchJobSubmitRequest(
                job_id="job-cancelled",
                integration_id="fs-a",
                items=[{"object_identity": "/tmp/b.txt"}],
            )
        )
    )
    job_service.cancel_job(cancelled.job.job_id)

    client = TestClient(app)
    response = client.get("/api/v1/ui/scan-results?state=cancelled")

    assert response.status_code == 200
    payload = response.json()
    assert [result["job"]["job_id"] for result in payload["results"]] == ["job-cancelled"]
    assert payload["results"][0]["progress"]["cancelled_items"] == 1


def test_ui_policies_lists_scope_and_integration_assignments() -> None:
    app = create_app()
    control_plane = app.state.control_plane_service
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="gcs-a",
            platform="gcs",
            platform_key="tenant-a",
            display_name="GCS A",
            config={
                "policy": {
                    "policy_id": "policy-default-gcs",
                    "malicious_verdict": {"action": "detect_only"},
                }
            },
        )
    )
    control_plane.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="gcs-a",
            scope_type="path",
            resource_selector="bucket-a",
            display_name="Bucket A",
            mode="full_scan",
            post_scan_policy={
                "policy_id": "policy-quarantine",
                "malicious_verdict": {"action": "quarantine", "tag_on_quarantine": True},
                "auto_dianna_on_verdicts": ["malicious"],
                "outcome_triggers": {"malicious": True, "not_scanned": True, "non_compliant": True},
                "non_compliance": {"blocked_file_types": ["windows_executable"]},
            },
        )
    )
    control_plane.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-b",
            integration_id="gcs-a",
            scope_type="path",
            resource_selector="bucket-b",
            display_name="Bucket B",
            mode="full_scan",
        )
    )

    client = TestClient(app)
    response = client.get("/api/v1/ui/policies")

    assert response.status_code == 200
    policies = {policy["policy_id"]: policy for policy in response.json()["policies"]}
    assert set(policies) == {"policy-default-gcs", "policy-quarantine"}
    assert policies["policy-quarantine"]["assigned_assets"] == 1
    assert policies["policy-quarantine"]["assignments"][0]["scope_id"] == "scope-a"
    assert policies["policy-quarantine"]["assignments"][0]["source"] == "scope"
    assert policies["policy-quarantine"]["outcome_rules"]["malicious_action"] == "quarantine"
    assert policies["policy-quarantine"]["outcome_rules"]["auto_dianna_on_verdicts"] == ["malicious"]
    assert policies["policy-quarantine"]["outcome_rules"]["outcome_triggers"]["not_scanned"] is True
    assert policies["policy-quarantine"]["outcome_rules"]["non_compliance"]["blocked_file_types"] == ["windows_executable"]
    assert policies["policy-default-gcs"]["assigned_assets"] == 1
    assert policies["policy-default-gcs"]["assignments"][0]["scope_id"] == "scope-b"
    assert policies["policy-default-gcs"]["assignments"][0]["source"] == "integration"


def test_ui_scope_policy_update_assigns_policy_to_protected_scope() -> None:
    app = create_app()
    control_plane = app.state.control_plane_service
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="fs-a",
            platform="filesystem",
            platform_key="local",
            display_name="Filesystem A",
            config={},
        )
    )
    control_plane.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="fs-a",
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance",
            mode="full_scan",
        )
    )

    client = TestClient(app)
    response = client.put(
        "/api/v1/ui/scopes/scope-a/policy",
        json={
            "policy": {
                "policy_id": "policy-finance",
                "malicious_verdict": {"action": "quarantine"},
                "non_compliant_treatment": "treat_as_malicious",
            }
        },
    )

    assert response.status_code == 200
    scope = response.json()
    assert scope["post_scan_policy"]["policy_id"] == "policy-finance"
    assert scope["post_scan_policy"]["malicious_verdict"]["action"] == "quarantine"

    policies = client.get("/api/v1/ui/policies").json()["policies"]
    assert len(policies) == 1
    assert policies[0]["policy_id"] == "policy-finance"
    assert policies[0]["assigned_assets"] == 1
    assert policies[0]["assignments"][0]["selector"] == "/finance"


def test_ui_operator_workflow_smoke_assets_policy_scan_results(monkeypatch) -> None:
    app = create_app()

    from dsx_connect_ng.api.routes import ui as ui_routes

    monkeypatch.setattr(
        ui_routes,
        "_probe_connector_health",
        lambda base_url, connector_name: ui_routes.ConnectorHealthStatus(
            status="healthy",
            endpoint=f"{base_url}/{connector_name}/healthz",
            details={"ok": True},
        ),
    )
    def fake_fetch_assets(
        base_url,
        connector_name,
        *,
        asset_type,
        source,
        limit,
        cursor,
        asset_filter_mode=None,
        asset_filter_value=None,
    ):
        return {
            "asset_type": asset_type,
            "source": source,
            "status": "success",
            "assets": [
                {"id": "bucket-a", "display_name": "Bucket A", "selector": "bucket-a"},
                {"id": "bucket-b", "display_name": "Bucket B", "selector": "bucket-b"},
            ],
            "next_cursor": None,
        }

    monkeypatch.setattr(ui_routes, "_fetch_connector_assets", fake_fetch_assets)

    client = TestClient(app)
    integration = client.post(
        "/api/v1/ui/integrations",
        json={
            "integration_id": "gcs-a",
            "platform": "gcs",
            "platform_key": "tenant-a",
            "display_name": "GCS A",
            "config": {
                "reader": {
                    "default_strategy": "proxy",
                    "proxy": {
                        "base_url": "http://127.0.0.1:8630",
                        "connector_name": "google-cloud-storage-connector",
                    },
                },
                "policy": {
                    "policy_id": "policy-default-gcs",
                    "malicious_verdict": {"action": "detect_only"},
                },
            },
        },
    )
    assert integration.status_code == 200

    connectors = client.get("/api/v1/ui/assets/connectors").json()["connectors"]
    assert connectors[0]["integration"]["integration_id"] == "gcs-a"
    assert connectors[0]["health"]["status"] == "healthy"

    before_scope = client.get("/api/v1/ui/assets/protected?connector_type=gcs&type=bucket")
    assert before_scope.status_code == 200
    assert [asset["coverage_state"] for asset in before_scope.json()["assets"]] == ["unprotected", "unprotected"]

    toggle_integration = client.post("/api/v1/ui/integrations/gcs-a/enabled", json={"enabled": False})
    assert toggle_integration.status_code == 200
    assert toggle_integration.json()["enabled"] is False
    toggle_integration = client.post("/api/v1/ui/integrations/gcs-a/enabled", json={"enabled": True})
    assert toggle_integration.status_code == 200
    assert toggle_integration.json()["enabled"] is True

    scope_response = client.post(
        "/api/v1/ui/assets/protected",
        json={
            "scope_id": "scope-bucket-a",
            "integration_id": "gcs-a",
            "scope_type": "path",
            "resource_selector": "bucket-a",
            "display_name": "Bucket A",
            "mode": "full_scan",
        },
    )
    assert scope_response.status_code == 200

    toggle_scope = client.post("/api/v1/ui/scopes/scope-bucket-a/enabled", json={"enabled": False})
    assert toggle_scope.status_code == 200
    assert toggle_scope.json()["enabled"] is False
    toggle_scope = client.post("/api/v1/ui/scopes/scope-bucket-a/enabled", json={"enabled": True})
    assert toggle_scope.status_code == 200
    assert toggle_scope.json()["enabled"] is True

    policy_response = client.put(
        "/api/v1/ui/scopes/scope-bucket-a/policy",
        json={
            "policy": {
                "policy_id": "policy-quarantine-malware",
                "malicious_verdict": {"action": "quarantine", "tag_on_quarantine": True},
                "auto_dianna_on_verdicts": ["malicious"],
            }
        },
    )
    assert policy_response.status_code == 200

    protected = client.get("/api/v1/ui/assets/protected?connector_type=gcs&type=bucket").json()["assets"]
    assert protected[0]["selector"] == "bucket-a"
    assert protected[0]["coverage_state"] == "protected"
    assert protected[0]["matching_scope_id"] == "scope-bucket-a"
    assert protected[0]["policy"]["policy_id"] == "policy-quarantine-malware"
    assert protected[1]["coverage_state"] == "unprotected"

    policies = client.get("/api/v1/ui/policies").json()["policies"]
    assert len(policies) == 1
    assert policies[0]["policy_id"] == "policy-quarantine-malware"
    assert policies[0]["assignments"][0]["selector"] == "bucket-a"
    assert policies[0]["outcome_rules"]["malicious_action"] == "quarantine"

    scan_response = client.post(
        "/api/v1/ui/scopes/scope-bucket-a/scan",
        json={"reader_strategy": "proxy", "path": "bucket-a/malware.exe"},
    )
    assert scan_response.status_code == 200
    job_id = scan_response.json()["job"]["job_id"]

    job_service = app.state.job_service
    scanned_item = job_service.list_job_items(job_id=job_id, limit=1)[0]
    job_service.complete_scan_only(
        scanned_item.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Malicious", "scanGuid": "scan-malware"}),
    )
    job_service.update_remediation_stage(
        scanned_item.job_item_id,
        StageUpdateRequest(state="completed", result={"action": "quarantine", "outcome": "success"}),
    )

    scan_results = client.get("/api/v1/ui/scan-results?integration_id=gcs-a&item_limit=10")
    assert scan_results.status_code == 200
    result = scan_results.json()["results"][0]
    assert result["job"]["job_id"] == job_id
    assert result["target"]["scope_id"] == "scope-bucket-a"
    assert result["target"]["label"] == "bucket-a"
    assert result["progress"]["percent_complete"] == 100.0
    assert result["findings"]["malicious"] == 1
    assert result["remediation"]["completed"] == 1
    assert result["cancel"]["immediate_file_level_cancel"] is False


def test_ui_demo_seed_creates_repeatable_local_preview_data() -> None:
    app = create_app()
    client = TestClient(app)

    first = client.post("/api/v1/ui/demo/seed")
    second = client.post("/api/v1/ui/demo/seed")

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert [row["integration_id"] for row in first_payload["integrations"]] == ["demo-gcs", "demo-filesystem"]
    assert [row["integration_id"] for row in second_payload["integrations"]] == ["demo-gcs", "demo-filesystem"]
    assert [row["scope_id"] for row in first_payload["scopes"]] == ["demo-scope-gcs-finance", "demo-scope-fs-legal"]
    assert [row["job"]["job_id"] for row in first_payload["jobs"]] == ["demo-job-gcs-scan", "demo-job-fs-cancelled"]

    connectors = client.get("/api/v1/ui/assets/connectors").json()["connectors"]
    assert [row["integration"]["integration_id"] for row in connectors] == ["demo-gcs", "demo-filesystem"]

    policies = client.get("/api/v1/ui/policies").json()["policies"]
    policy_ids = {policy["policy_id"] for policy in policies}
    assert {"demo-detect-only", "demo-quarantine-malware"} <= policy_ids

    results = client.get("/api/v1/ui/scan-results?item_limit=10").json()["results"]
    assert [result["job"]["job_id"] for result in results] == ["demo-job-fs-cancelled", "demo-job-gcs-scan"]
    gcs_result = next(result for result in results if result["job"]["job_id"] == "demo-job-gcs-scan")
    assert gcs_result["findings"]["clean"] == 1
    assert gcs_result["findings"]["suspicious"] == 1
    assert gcs_result["findings"]["malicious"] == 1
    assert gcs_result["remediation"]["completed"] == 1


def test_ui_demo_seed_rejects_non_dev_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "prod")
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/v1/ui/demo/seed")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "demo_seed_disabled"
