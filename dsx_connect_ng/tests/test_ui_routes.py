from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dsx_connect_ng.app import create_app
from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.models import IntegrationCreate, ProtectedScopeCreate


@pytest.fixture(autouse=True)
def force_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "control_plane_backend", "memory")
    monkeypatch.setattr(settings, "job_bus_backend", "memory")


def test_operator_console_page_renders() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/ui/")

    assert response.status_code == 200
    assert "DSX-Connect NG Operator Console" in response.text


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

    monkeypatch.setattr(
        ui_routes,
        "_fetch_connector_assets",
        lambda base_url, connector_name, *, asset_type, source, limit, cursor: {
            "asset_type": "bucket",
            "source": source,
            "status": "success",
            "assets": [
                {"id": "bucket-a", "display_name": "Bucket A", "selector": "bucket-a", "metadata": {"provider": "gcs"}},
                {"id": "bucket-b", "display_name": "Bucket B", "selector": "bucket-b", "metadata": {"provider": "gcs"}},
            ],
            "next_cursor": None,
        },
    )

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
