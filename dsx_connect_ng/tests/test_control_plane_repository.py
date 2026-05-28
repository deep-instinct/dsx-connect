from dsx_connect_ng.control_plane.models import (
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
