from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from dsx_connect_ng.app import create_app
from dsx_connect_ng.config import settings


@pytest.fixture(autouse=True)
def force_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "control_plane_backend", "memory")
    monkeypatch.setattr(settings, "job_bus_backend", "memory")
    monkeypatch.setattr(settings, "connector_registration_auth_enabled", False)
    monkeypatch.setattr(settings, "connector_enrollment_tokens", "")
    monkeypatch.setattr(settings.gateway, "auth_enabled", False)
    monkeypatch.setattr(settings.gateway, "allow_anonymous", True)
    monkeypatch.setattr(settings.gateway, "static_clients_json", "")
    monkeypatch.setattr(settings.gateway, "anonymous_principal_json", "")


def test_file_gateway_lists_enabled_scope_destinations() -> None:
    client = TestClient(create_app())
    integration = client.post(
        "/api/v1/control-plane/integrations",
        json={
            "platform": "gcs",
            "platform_key": "project-a",
            "display_name": "Project A",
            "capability_read": True,
            "capability_remediate": True,
            "config": {"capabilities": {"write": True}},
        },
    ).json()
    scope = client.post(
        "/api/v1/control-plane/scopes",
        json={
            "integration_id": integration["integration_id"],
            "scope_type": "path",
            "resource_selector": "claims-bucket/incoming",
            "display_name": "Claims Intake",
            "mode": "full_scan",
            "enabled": True,
            "post_scan_policy": {"classification": "internal"},
        },
    ).json()

    response = client.get("/api/v1/files/destinations")

    assert response.status_code == 200
    destinations = response.json()["destinations"]
    assert len(destinations) == 1
    assert destinations[0]["id"] == scope["scope_id"]
    assert destinations[0]["display_name"] == "Claims Intake"
    assert destinations[0]["capabilities"] == ["scan", "read", "write", "remediate"]
    assert destinations[0]["classification"] == "internal"


def test_file_gateway_transfer_upload_creates_cached_scan_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings.gateway, "upload_cache_dir", str(tmp_path))
    client = TestClient(create_app())
    integration = client.post(
        "/api/v1/control-plane/integrations",
        json={
            "platform": "filesystem",
            "platform_key": "lab",
            "display_name": "Lab Files",
            "capability_read": True,
            "config": {"capabilities": {"write": True}},
        },
    ).json()
    scope = client.post(
        "/api/v1/control-plane/scopes",
        json={
            "integration_id": integration["integration_id"],
            "scope_type": "path",
            "resource_selector": "/app/scan",
            "display_name": "Lab Uploads",
            "mode": "full_scan",
            "enabled": True,
        },
    ).json()

    response = client.post(
        "/api/v1/files/transfers",
        data={
            "destination_id": scope["scope_id"],
            "destination_path": "claims",
            "metadata": (
                '{"tenant_id":"tenant-a","application":"desktop-mvp",'
                '"cost_center":"CC-10","billing_code":"BU-APP",'
                '"dsxa_protected_entity_id":65}'
            ),
        },
        files=[
            ("files", ("report.txt", b"hello", "text/plain")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["submitted_files"] == 1
    assert body["destination_id"] == scope["scope_id"]
    assert body["job"]["job"]["job_type"] == "file.transfer"
    assert body["status_url"].endswith(f"/execution/jobs/{body['job_id']}/progress")

    items = client.get(f"/api/v1/execution/jobs/{body['job_id']}/items").json()
    assert len(items) == 1
    assert items[0]["content_source"]["mode"] == "cached"
    cached_path = Path(items[0]["content_source"]["locator"])
    assert cached_path.exists()
    assert cached_path.read_bytes() == b"hello"
    assert items[0]["payload"]["readerStrategy"] == "cached"
    assert items[0]["payload"]["deliveryTarget"]["destinationId"] == scope["scope_id"]
    attribution = items[0]["payload"]["attribution"]
    assert attribution["tenant_id"] == "tenant-a"
    assert attribution["application_id"] == "desktop-mvp"
    assert attribution["application_name"] == "desktop-mvp"
    assert attribution["cost_center"] == "CC-10"
    assert attribution["billing_code"] == "BU-APP"
    assert attribution["destination_id"] == scope["scope_id"]
    assert attribution["destination_platform"] == "filesystem"
    assert attribution["protected_target"] == "/app/scan"
    assert attribution["file_name"] == "report.txt"
    assert attribution["file_size_bytes"] == 5
    assert attribution["file_sha256"] == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert items[0]["payload"]["protectedEntity"] == 65


def test_file_gateway_static_token_filters_destinations_and_applies_attribution(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings.gateway, "upload_cache_dir", str(tmp_path))
    monkeypatch.setattr(settings.gateway, "auth_enabled", True)
    monkeypatch.setattr(settings.gateway, "allow_anonymous", False)
    client = TestClient(create_app())
    integration = client.post(
        "/api/v1/control-plane/integrations",
        json={
            "platform": "filesystem",
            "platform_key": "lab",
            "display_name": "Lab Files",
            "capability_read": True,
            "config": {"capabilities": {"write": True}},
        },
    ).json()
    allowed_scope = client.post(
        "/api/v1/control-plane/scopes",
        json={
            "integration_id": integration["integration_id"],
            "scope_type": "path",
            "resource_selector": "/app/allowed",
            "display_name": "Allowed Uploads",
            "mode": "full_scan",
            "enabled": True,
        },
    ).json()
    denied_scope = client.post(
        "/api/v1/control-plane/scopes",
        json={
            "integration_id": integration["integration_id"],
            "scope_type": "path",
            "resource_selector": "/app/denied",
            "display_name": "Denied Uploads",
            "mode": "full_scan",
            "enabled": True,
        },
    ).json()
    monkeypatch.setattr(
        settings.gateway,
        "static_clients_json",
        json.dumps(
            [
                {
                    "token": "claims-token",
                    "principal_id": "app_claims",
                    "tenant_id": "tenant-from-token",
                    "application_id": "claims-portal",
                    "application_name": "Claims Portal",
                    "cost_center": "CC-TOKEN",
                    "billing_code": "BILL-TOKEN",
                    "dsxa_protected_entity_id": 91,
                    "grants": [
                        {
                            "destination_ids": [allowed_scope["scope_id"]],
                            "actions": ["discover", "submit", "status"],
                            "path_prefixes": ["claims/inbound"],
                        }
                    ],
                }
            ]
        ),
    )

    no_token = client.get("/api/v1/files/destinations")
    assert no_token.status_code == 401

    listed = client.get("/api/v1/files/destinations", headers={"Authorization": "Bearer claims-token"})
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["destinations"]] == [allowed_scope["scope_id"]]

    denied = client.post(
        "/api/v1/files/transfers",
        headers={"Authorization": "Bearer claims-token"},
        data={
            "destination_id": denied_scope["scope_id"],
            "destination_path": "claims/inbound",
        },
        files=[("files", ("report.txt", b"hello", "text/plain"))],
    )
    assert denied.status_code == 403

    bad_path = client.post(
        "/api/v1/files/transfers",
        headers={"Authorization": "Bearer claims-token"},
        data={
            "destination_id": allowed_scope["scope_id"],
            "destination_path": "legal/inbound",
        },
        files=[("files", ("report.txt", b"hello", "text/plain"))],
    )
    assert bad_path.status_code == 403

    accepted = client.post(
        "/api/v1/files/transfers",
        headers={"Authorization": "Bearer claims-token"},
        data={
            "destination_id": allowed_scope["scope_id"],
            "destination_path": "claims/inbound",
            "metadata": '{"tenant_id":"request-tenant","application":"request-app","cost_center":"CC-REQUEST"}',
        },
        files=[("files", ("report.txt", b"hello", "text/plain"))],
    )
    assert accepted.status_code == 200
    job_id = accepted.json()["job_id"]
    items = client.get(f"/api/v1/execution/jobs/{job_id}/items").json()
    attribution = items[0]["payload"]["attribution"]
    assert attribution["principal_id"] == "app_claims"
    assert attribution["auth_method"] == "static_bearer"
    assert attribution["tenant_id"] == "tenant-from-token"
    assert attribution["application_id"] == "claims-portal"
    assert attribution["application_name"] == "Claims Portal"
    assert attribution["cost_center"] == "CC-TOKEN"
    assert attribution["billing_code"] == "BILL-TOKEN"
    assert attribution["dsxa_protected_entity_id"] == 91
    assert items[0]["payload"]["protectedEntity"] == 91


def test_file_gateway_static_token_resolves_onboarded_application_before_static_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings.gateway, "upload_cache_dir", str(tmp_path))
    monkeypatch.setattr(settings.gateway, "auth_enabled", True)
    monkeypatch.setattr(settings.gateway, "allow_anonymous", False)
    monkeypatch.setattr(
        settings.gateway,
        "static_clients_json",
        json.dumps(
            [
                {
                    "token": "shared-token",
                    "principal_id": "legacy-static-json",
                    "tenant_id": "legacy-tenant",
                    "grants": [{"actions": ["discover", "submit", "status"]}],
                }
            ]
        ),
    )
    client = TestClient(create_app())
    integration = client.post(
        "/api/v1/control-plane/integrations",
        json={
            "platform": "gcs",
            "platform_key": "project-a",
            "display_name": "Project A",
            "capability_read": True,
            "config": {"capabilities": {"write": True}},
        },
    ).json()
    scope = client.post(
        "/api/v1/control-plane/scopes",
        json={
            "integration_id": integration["integration_id"],
            "scope_type": "path",
            "resource_selector": "claims-bucket",
            "display_name": "Claims Bucket",
            "mode": "full_scan",
            "enabled": True,
        },
    ).json()
    app_response = client.post(
        "/api/v1/control-plane/gateway-applications",
        json={
            "application_id": "claims-upload-service",
            "display_name": "Claims Upload Service",
            "tenant_id": "claims-tenant",
            "customer_id": "internal",
            "business_unit": "Claims",
            "cost_center": "CC-1042",
            "billing_code": "CLAIMS-PROD",
            "default_protected_entity_id": 65,
            "identity_bindings": [
                {
                    "provider": "static_bearer",
                    "token": "shared-token",
                }
            ],
            "grants": [
                {
                    "destination_ids": [scope["scope_id"]],
                    "actions": ["discover", "submit", "status"],
                }
            ],
        },
    )
    assert app_response.status_code == 200

    listed = client.get("/api/v1/files/destinations", headers={"Authorization": "Bearer shared-token"})
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["destinations"]] == [scope["scope_id"]]

    accepted = client.post(
        "/api/v1/files/transfers",
        headers={"Authorization": "Bearer shared-token"},
        data={
            "destination_id": scope["scope_id"],
            "destination_path": "inbound",
        },
        files=[("files", ("report.txt", b"hello", "text/plain"))],
    )
    assert accepted.status_code == 200
    job_id = accepted.json()["job_id"]
    items = client.get(f"/api/v1/execution/jobs/{job_id}/items").json()
    attribution = items[0]["payload"]["attribution"]
    assert attribution["principal_id"] == "claims-upload-service"
    assert attribution["application_id"] == "claims-upload-service"
    assert attribution["application_name"] == "Claims Upload Service"
    assert attribution["tenant_id"] == "claims-tenant"
    assert attribution["customer_id"] == "internal"
    assert attribution["business_unit"] == "Claims"
    assert attribution["cost_center"] == "CC-1042"
    assert attribution["billing_code"] == "CLAIMS-PROD"
    assert attribution["dsxa_protected_entity_id"] == 65
    assert items[0]["payload"]["protectedEntity"] == 65
