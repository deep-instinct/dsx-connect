from fastapi import HTTPException

from dsx_connect_ng.control_plane.models import (
    ConnectorInstanceHeartbeat,
    ConnectorInstanceRegister,
    IntegrationCreate,
    IntegrationUpdate,
    ProtectedScopeCreate,
    ProtectedScopeUpdate,
)
from dsx_connect_ng.control_plane.repository import InMemoryControlPlaneRepository
from dsx_connect_ng.control_plane.service import ControlPlaneService, normalize_selector, selectors_overlap


def build_service() -> ControlPlaneService:
    return ControlPlaneService(repo=InMemoryControlPlaneRepository())


def test_normalize_selector_for_path() -> None:
    assert normalize_selector("path", "///finance//loans///2026/") == "/finance/loans/2026"


def test_selectors_overlap_for_paths() -> None:
    assert selectors_overlap("path", "/finance", "/finance/loans")
    assert selectors_overlap("path", "/finance/loans", "/finance")
    assert not selectors_overlap("path", "/finance", "/hr")


def test_create_integration_rejects_duplicate_platform_key() -> None:
    service = build_service()
    payload = IntegrationCreate(
        platform="sharepoint",
        platform_key="tenant-a",
        display_name="Tenant A",
    )
    service.create_integration(payload)
    try:
        service.create_integration(payload)
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "integration_platform_key_conflict"
    else:
        raise AssertionError("expected duplicate integration conflict")


def test_register_connector_instance_creates_logical_integration() -> None:
    service = build_service()

    connector = service.register_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="gcs-pod-1",
            platform="gcs",
            platform_key="project-a",
            display_name="Project A",
            connector_name="google-cloud-storage-connector",
            connector_version="0.5.55",
            base_url="http://gcs:80",
            capabilities={"discover": True, "read": True, "write": True, "remediate": True},
            health="healthy",
            labels={"namespace": "dsx-connect"},
        )
    )

    integrations = service.list_integrations()
    assert len(integrations) == 1
    assert connector.integration_id == integrations[0].integration_id
    assert integrations[0].platform == "gcs"
    assert integrations[0].platform_key == "project-a"
    assert integrations[0].capability_discover is True
    assert integrations[0].capability_read is True
    assert integrations[0].capability_remediate is True


def test_register_connector_instance_reuses_existing_integration_and_heartbeat_updates_status() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(platform="filesystem", platform_key="host-a", display_name="Host A")
    )

    registered = service.register_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="fs-pod-1",
            integration_id=integration.integration_id,
            platform="filesystem",
            platform_key="host-a",
            connector_name="filesystem-connector",
            base_url="http://filesystem:80",
            capabilities={"discover": True, "read": True},
        )
    )
    assert registered.integration_id == integration.integration_id

    heartbeat = service.heartbeat_connector_instance(
        "fs-pod-1",
        ConnectorInstanceHeartbeat(
            health="healthy",
            connector_version="0.5.56",
            capabilities={"discover": True, "read": True, "write": False},
        ),
    )
    assert heartbeat.health == "healthy"
    assert heartbeat.connector_version == "0.5.56"
    assert heartbeat.capabilities["write"] is False
    assert len(service.list_connector_instances(integration_id=integration.integration_id)) == 1


def test_register_connector_instance_rejects_explicit_integration_mismatch() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(platform="gcs", platform_key="project-a", display_name="Project A")
    )

    try:
        service.register_connector_instance(
            ConnectorInstanceRegister(
                connector_instance_id="gcs-pod-1",
                integration_id=integration.integration_id,
                platform="gcs",
                platform_key="project-b",
                connector_name="google-cloud-storage-connector",
                base_url="http://gcs:80",
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "connector_integration_mismatch"
    else:
        raise AssertionError("expected connector integration mismatch")


def test_create_scope_rejects_overlapping_path_scope() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(
            platform="s3",
            platform_key="account-a",
            display_name="S3 Account A",
        )
    )
    service.create_scope(
        ProtectedScopeCreate(
            integration_id=integration.integration_id,
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance",
            mode="monitor",
        )
    )
    try:
        service.create_scope(
            ProtectedScopeCreate(
                integration_id=integration.integration_id,
                scope_type="path",
                resource_selector="/finance/loans",
                display_name="Loans",
                mode="monitor",
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "scope_overlap"
    else:
        raise AssertionError("expected overlapping scope conflict")


def test_create_scope_allows_same_selector_in_different_integrations() -> None:
    service = build_service()
    left = service.create_integration(
        IntegrationCreate(platform="s3", platform_key="left", display_name="Left")
    )
    right = service.create_integration(
        IntegrationCreate(platform="s3", platform_key="right", display_name="Right")
    )
    service.create_scope(
        ProtectedScopeCreate(
            integration_id=left.integration_id,
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance Left",
            mode="monitor",
        )
    )
    scope = service.create_scope(
        ProtectedScopeCreate(
            integration_id=right.integration_id,
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance Right",
            mode="monitor",
        )
    )
    assert scope.integration_id == right.integration_id


def test_create_integration_rejects_invalid_runtime_policy_config() -> None:
    service = build_service()
    try:
        service.create_integration(
            IntegrationCreate(
                platform="filesystem",
                platform_key="host-x",
                display_name="Host X",
                config={
                    "policy": {
                        "auto_dianna_on_verdicts": ["definitely_bad"],
                    }
                },
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail["code"] == "invalid_integration_runtime_config"
    else:
        raise AssertionError("expected invalid integration runtime config")


def test_update_integration_rejects_invalid_runtime_policy_config() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(platform="filesystem", platform_key="host-y", display_name="Host Y")
    )
    try:
        service.update_integration(
            integration.integration_id,
            IntegrationUpdate(
                config={
                    "policy": {
                        "content_preservation_mode_by_verdict": {
                            "malicious": "archive",
                        }
                    }
                }
            ),
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail["code"] == "invalid_integration_runtime_config"
    else:
        raise AssertionError("expected invalid integration update config")


def test_update_scope_preserves_existing_overlap_validity_for_self() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(platform="filesystem", platform_key="host-a", display_name="Host A")
    )
    scope = service.create_scope(
        ProtectedScopeCreate(
            integration_id=integration.integration_id,
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance",
            mode="monitor",
        )
    )
    updated = service.update_scope(
        scope.scope_id,
        ProtectedScopeUpdate(display_name="Finance Updated", enabled=False),
    )
    assert updated.display_name == "Finance Updated"
    assert updated.enabled is False


def test_create_scope_rejects_invalid_post_scan_policy_config() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(platform="filesystem", platform_key="host-c", display_name="Host C")
    )
    try:
        service.create_scope(
            ProtectedScopeCreate(
                integration_id=integration.integration_id,
                scope_type="path",
                resource_selector="/finance",
                display_name="Finance",
                mode="monitor",
                post_scan_policy={
                    "result_delivery_policy": {
                        "scan": "sometimes",
                    }
                },
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail["code"] == "invalid_scope_policy_config"
    else:
        raise AssertionError("expected invalid scope policy config")


def test_update_scope_rejects_invalid_post_scan_policy_config() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(platform="filesystem", platform_key="host-d", display_name="Host D")
    )
    scope = service.create_scope(
        ProtectedScopeCreate(
            integration_id=integration.integration_id,
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance",
            mode="monitor",
        )
    )
    try:
        service.update_scope(
            scope.scope_id,
            ProtectedScopeUpdate(
                post_scan_policy={
                    "auto_dianna_on_verdicts": ["unknown_bad"],
                }
            ),
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail["code"] == "invalid_scope_policy_config"
    else:
        raise AssertionError("expected invalid scope policy update config")


def test_match_scope_returns_longest_path_prefix_match() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(platform="filesystem", platform_key="host-b", display_name="Host B")
    )
    service.create_scope(
        ProtectedScopeCreate(
            integration_id=integration.integration_id,
            scope_type="path",
            resource_selector="/legal/contracts",
            display_name="Contracts",
            mode="monitor",
        )
    )
    matched = service.match_scope(
        integration_id=integration.integration_id,
        scope_type="path",
        resource_selector="/legal/contracts/2026/q2.pdf",
    )
    assert matched is not None
    assert matched.display_name == "Contracts"


def test_match_scope_returns_none_when_not_scoped() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(platform="s3", platform_key="acct-b", display_name="Account B")
    )
    matched = service.match_scope(
        integration_id=integration.integration_id,
        scope_type="path",
        resource_selector="/unscoped/path",
    )
    assert matched is None


def test_match_scope_matches_identity_exactly() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(platform="sharepoint", platform_key="tenant-b", display_name="Tenant B")
    )
    scope = service.create_scope(
        ProtectedScopeCreate(
            integration_id=integration.integration_id,
            scope_type="identity",
            resource_selector="site-123/drive-456/item-789",
            display_name="Item Scope",
            mode="monitor",
        )
    )
    matched = service.match_scope(
        integration_id=integration.integration_id,
        scope_type="identity",
        resource_selector="site-123/drive-456/item-789",
    )
    assert matched is not None
    assert matched.scope_id == scope.scope_id
