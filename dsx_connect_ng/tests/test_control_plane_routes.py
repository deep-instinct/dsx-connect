import pytest
from fastapi.testclient import TestClient

from dsx_connect_ng.app import create_app
from dsx_connect_ng.config import settings


@pytest.fixture(autouse=True)
def force_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "control_plane_backend", "memory")
    monkeypatch.setattr(settings, "job_bus_backend", "memory")


def test_control_plane_connector_registration_routes() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/control-plane/connectors/register",
        json={
            "connector_instance_id": "gcs-pod-1",
            "platform": "gcs",
            "platform_key": "project-a",
            "display_name": "Project A",
            "connector_name": "google-cloud-storage-connector",
            "connector_version": "0.5.55",
            "base_url": "http://gcs:80",
            "capabilities": {"discover": True, "read": True, "write": True},
            "health": "healthy",
            "labels": {"namespace": "dsx-connect"},
        },
    )

    assert response.status_code == 200
    registered = response.json()
    assert registered["connector_instance_id"] == "gcs-pod-1"
    assert registered["integration_id"]

    integrations = client.get("/api/v1/control-plane/integrations").json()
    assert [row["integration_id"] for row in integrations] == [registered["integration_id"]]
    assert integrations[0]["platform"] == "gcs"
    assert integrations[0]["capability_read"] is True

    heartbeat = client.post(
        "/api/v1/control-plane/connectors/gcs-pod-1/heartbeat",
        json={"health": "degraded", "labels": {"pod": "gcs-pod-1"}},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["health"] == "degraded"
    assert heartbeat.json()["labels"] == {"pod": "gcs-pod-1"}

    connectors = client.get("/api/v1/control-plane/connectors").json()
    assert [row["connector_instance_id"] for row in connectors] == ["gcs-pod-1"]


def test_control_plane_connector_registration_rejects_mismatched_integration() -> None:
    client = TestClient(create_app())
    integration = client.post(
        "/api/v1/control-plane/integrations",
        json={
            "platform": "gcs",
            "platform_key": "project-a",
            "display_name": "Project A",
        },
    ).json()

    response = client.post(
        "/api/v1/control-plane/connectors/register",
        json={
            "connector_instance_id": "gcs-pod-1",
            "integration_id": integration["integration_id"],
            "platform": "gcs",
            "platform_key": "project-b",
            "connector_name": "google-cloud-storage-connector",
            "base_url": "http://gcs:80",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "connector_integration_mismatch"
