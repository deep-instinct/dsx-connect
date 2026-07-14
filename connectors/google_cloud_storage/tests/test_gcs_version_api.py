import pytest
from fastapi.testclient import TestClient

pytest.importorskip("google.cloud.storage")


def test_gcs_connector_version_endpoint_reports_packaged_version() -> None:
    from connectors.framework import dsx_connector as framework
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    client = TestClient(framework.connector_api)

    response = client.get("/google-cloud-storage-connector/version")

    assert response.status_code == 200
    assert response.json() == {
        "connector_name": "google-cloud-storage-connector",
        "connector_id": "google-cloud-storage-connector",
        "connector_instance_id": gc.connector.connector_instance_id,
        "version": gc.CONNECTOR_VERSION,
    }
