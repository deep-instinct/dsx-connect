from dsx_connect_ng.control_plane.models import (
    ConnectorInstanceHeartbeat,
    ConnectorInstanceRegister,
    IntegrationCreate,
    IntegrationUpdate,
    ProtectedScopeCreate,
    ProtectedScopeUpdate,
)
from dsx_connect_ng.control_plane.repository import InMemoryControlPlaneRepository


def test_inmemory_repository_integration_crud() -> None:
    repo = InMemoryControlPlaneRepository()
    created = repo.create_integration(
        IntegrationCreate(
            platform="sharepoint",
            platform_key="tenant-a",
            display_name="Tenant A",
            capability_read=True,
            capability_remediate=True,
            config={
                "remediation": {
                    "supports_delete": True,
                    "supports_move": True,
                }
            },
        )
    )
    assert repo.get_integration(created.integration_id) is not None
    assert created.remediation_capabilities.supports_delete is True
    assert created.remediation_capabilities.supports_move is True
    assert created.remediation_capabilities.supports_tag is False

    updated = repo.update_integration(
        created.integration_id,
        IntegrationUpdate(display_name="Tenant A Updated", enabled=False),
    )
    assert updated is not None
    assert updated.display_name == "Tenant A Updated"
    assert updated.enabled is False
    assert len(repo.list_integrations()) == 1


def test_inmemory_repository_connector_instance_upsert_and_heartbeat() -> None:
    repo = InMemoryControlPlaneRepository()
    integration = repo.create_integration(
        IntegrationCreate(platform="gcs", platform_key="project-a", display_name="Project A")
    )
    registered = repo.upsert_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="gcs-pod-1",
            integration_id=integration.integration_id,
            platform="gcs",
            platform_key="project-a",
            connector_name="google-cloud-storage-connector",
            connector_version="0.5.55",
            base_url="http://gcs:80",
            capabilities={"discover": True, "read": True, "write": True},
            health="healthy",
            labels={"namespace": "dsx-connect"},
        ),
        integration_id=integration.integration_id,
    )

    assert registered.connector_instance_id == "gcs-pod-1"
    assert registered.integration_id == integration.integration_id
    assert repo.get_connector_instance("gcs-pod-1") is not None
    assert len(repo.list_connector_instances(integration_id=integration.integration_id)) == 1

    upserted = repo.upsert_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="gcs-pod-1",
            integration_id=integration.integration_id,
            platform="gcs",
            platform_key="project-a",
            connector_name="google-cloud-storage-connector",
            connector_version="0.5.56",
            base_url="http://gcs:80",
            capabilities={"discover": True, "read": True, "write": True, "remediate": True},
            health="degraded",
        ),
        integration_id=integration.integration_id,
    )
    assert upserted.connector_version == "0.5.56"
    assert upserted.capabilities["remediate"] is True
    assert len(repo.list_connector_instances()) == 1

    heartbeat = repo.update_connector_instance_heartbeat(
        "gcs-pod-1",
        ConnectorInstanceHeartbeat(health="healthy", connector_version="0.5.57", labels={"pod": "gcs-pod-1"}),
    )
    assert heartbeat is not None
    assert heartbeat.health == "healthy"
    assert heartbeat.connector_version == "0.5.57"
    assert heartbeat.labels == {"pod": "gcs-pod-1"}


def test_inmemory_repository_scope_crud() -> None:
    repo = InMemoryControlPlaneRepository()
    integration = repo.create_integration(
        IntegrationCreate(platform="s3", platform_key="acct-a", display_name="Account A")
    )
    scope = repo.create_scope(
        ProtectedScopeCreate(
            integration_id=integration.integration_id,
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance",
            mode="monitor",
        ),
        normalized_selector="/finance",
    )
    assert repo.get_scope(scope.scope_id) is not None

    updated = repo.update_scope(
        scope.scope_id,
        ProtectedScopeUpdate(display_name="Finance Updated", mode="full_scan"),
        normalized_selector="/finance",
    )
    assert updated is not None
    assert updated.display_name == "Finance Updated"
    assert updated.mode == "full_scan"
    assert len(repo.list_scopes(integration_id=integration.integration_id)) == 1
