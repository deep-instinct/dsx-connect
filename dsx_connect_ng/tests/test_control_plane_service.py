from fastapi import HTTPException

from dsx_connect_ng.control_plane.models import (
    ConnectorInstanceHeartbeat,
    ConnectorInstanceRegister,
    GatewayApplicationCreate,
    GatewayApplicationGrant,
    GatewayApplicationIdentityBinding,
    GatewayApplicationUpdate,
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
            base_url="http://0.0.0.0:8595/google-cloud-storage-connector",
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
    assert integrations[0].config["reader"]["default_strategy"] == "proxy"
    assert (
        integrations[0].config["reader"]["proxy"]["endpoint_url"]
        == "http://127.0.0.1:8595/google-cloud-storage-connector/read_file"
    )
    assert integrations[0].config["reader"]["proxy"]["base_url"] == "http://127.0.0.1:8595/google-cloud-storage-connector"
    assert integrations[0].config["reader"]["proxy"]["connector_name"] == "google-cloud-storage-connector"


def test_register_connector_instance_backfills_reader_config_for_existing_empty_integration() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(
            platform="filesystem",
            platform_key="host-a",
            display_name="Host A",
            config={},
        )
    )

    service.register_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="fs-pod-1",
            integration_id=integration.integration_id,
            platform="filesystem",
            platform_key="host-a",
            connector_name="filesystem-connector",
            base_url="http://filesystem-filesystem-connector/filesystem-connector",
            capabilities={"discover": True, "read": True},
        )
    )

    updated = service.get_integration_or_404(integration.integration_id)
    assert updated.config["reader"]["default_strategy"] == "proxy"
    assert (
        updated.config["reader"]["proxy"]["endpoint_url"]
        == "http://filesystem-filesystem-connector/filesystem-connector/read_file"
    )
    assert updated.config["reader"]["proxy"]["base_url"] == "http://filesystem-filesystem-connector/filesystem-connector"
    assert updated.config["reader"]["proxy"]["connector_name"] == "filesystem-connector"


def test_register_connector_instance_preserves_existing_reader_config() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(
            platform="gcs",
            platform_key="project-a",
            display_name="Project A",
            config={"reader": {"default_strategy": "native"}},
        )
    )

    service.register_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="gcs-pod-1",
            integration_id=integration.integration_id,
            platform="gcs",
            platform_key="project-a",
            connector_name="google-cloud-storage-connector",
            base_url="http://gcs:80",
            capabilities={"discover": True, "read": True},
        )
    )

    updated = service.get_integration_or_404(integration.integration_id)
    assert updated.config == {"reader": {"default_strategy": "native"}}


def test_connector_heartbeat_backfills_reader_config_for_existing_empty_integration() -> None:
    service = build_service()
    integration = service.create_integration(
        IntegrationCreate(
            platform="gcs",
            platform_key="project-a",
            display_name="Project A",
            config={},
        )
    )
    service.register_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id="gcs-pod-1",
            integration_id=integration.integration_id,
            platform="gcs",
            platform_key="project-a",
            connector_name="google-cloud-storage-connector",
            base_url="http://gcs-google-cloud-storage-connector/google-cloud-storage-connector",
            capabilities={"discover": True},
        )
    )

    service.heartbeat_connector_instance(
        "gcs-pod-1",
        ConnectorInstanceHeartbeat(capabilities={"discover": True, "read": True}),
    )

    updated = service.get_integration_or_404(integration.integration_id)
    assert updated.config["reader"]["default_strategy"] == "proxy"
    assert (
        updated.config["reader"]["proxy"]["endpoint_url"]
        == "http://gcs-google-cloud-storage-connector/google-cloud-storage-connector/read_file"
    )


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


def test_gateway_application_onboarding_round_trip_and_static_token_lookup() -> None:
    service = build_service()
    app = service.create_gateway_application(
        GatewayApplicationCreate(
            application_id="claims-upload-service",
            display_name="Claims Upload Service",
            tenant_id="claims",
            cost_center="CC-1042",
            billing_code="CLAIMS-PROD",
            default_protected_entity_id=65,
            identity_bindings=[
                GatewayApplicationIdentityBinding(
                    provider="static_bearer",
                    token="claims-token",
                )
            ],
            grants=[
                GatewayApplicationGrant(
                    destination_ids=["scope-claims"],
                    actions=["discover", "submit", "status"],
                    path_prefixes=["inbound"],
                )
            ],
        )
    )

    assert app.application_id == "claims-upload-service"
    assert service.get_gateway_application_or_404("claims-upload-service").cost_center == "CC-1042"
    assert service.find_gateway_application_by_static_token("claims-token") == app

    updated = service.update_gateway_application(
        "claims-upload-service",
        GatewayApplicationUpdate(enabled=False),
    )
    assert updated.enabled is False
    assert service.find_gateway_application_by_static_token("claims-token") is None


def test_gateway_application_rejects_duplicate_static_bearer_token_on_create() -> None:
    service = build_service()
    service.create_gateway_application(
        GatewayApplicationCreate(
            application_id="claims-upload-service",
            identity_bindings=[
                GatewayApplicationIdentityBinding(
                    provider="static_bearer",
                    token="claims-token",
                )
            ],
        )
    )
    try:
        service.create_gateway_application(
            GatewayApplicationCreate(
                application_id="finance-upload-service",
                identity_bindings=[
                    GatewayApplicationIdentityBinding(
                        provider="static_bearer",
                        token="claims-token",
                    )
                ],
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "gateway_application_token_conflict"
        assert exc.detail["application_ids"] == ["claims-upload-service"]
        assert exc.detail["tokens"] == ["claims-token"]
    else:
        raise AssertionError("expected gateway application token conflict")


def test_gateway_application_rejects_duplicate_static_bearer_token_on_update() -> None:
    service = build_service()
    service.create_gateway_application(
        GatewayApplicationCreate(
            application_id="claims-upload-service",
            identity_bindings=[
                GatewayApplicationIdentityBinding(
                    provider="static_bearer",
                    token="claims-token",
                )
            ],
        )
    )
    service.create_gateway_application(
        GatewayApplicationCreate(
            application_id="finance-upload-service",
            identity_bindings=[
                GatewayApplicationIdentityBinding(
                    provider="static_bearer",
                    token="finance-token",
                )
            ],
        )
    )
    try:
        service.update_gateway_application(
            "finance-upload-service",
            GatewayApplicationUpdate(
                identity_bindings=[
                    GatewayApplicationIdentityBinding(
                        provider="static_bearer",
                        token="claims-token",
                    )
                ]
            ),
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "gateway_application_token_conflict"
        assert exc.detail["application_ids"] == ["claims-upload-service"]
        assert exc.detail["tokens"] == ["claims-token"]
    else:
        raise AssertionError("expected gateway application token conflict")


def test_gateway_application_lookup_rejects_duplicate_tokens_in_existing_data() -> None:
    service = build_service()
    service.repo.create_gateway_application(
        GatewayApplicationCreate(
            application_id="claims-upload-service",
            identity_bindings=[
                GatewayApplicationIdentityBinding(
                    provider="static_bearer",
                    token="claims-token",
                )
            ],
        )
    )
    service.repo.create_gateway_application(
        GatewayApplicationCreate(
            application_id="finance-upload-service",
            identity_bindings=[
                GatewayApplicationIdentityBinding(
                    provider="static_bearer",
                    token="claims-token",
                )
            ],
        )
    )

    try:
        service.find_gateway_application_by_static_token("claims-token")
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "gateway_application_token_conflict"
        assert exc.detail["application_ids"] == ["claims-upload-service", "finance-upload-service"]
        assert exc.detail["token"] == "claims-token"
    else:
        raise AssertionError("expected gateway application token conflict")


def test_create_gateway_application_rejects_duplicate_application_id() -> None:
    service = build_service()
    payload = GatewayApplicationCreate(
        application_id="claims-upload-service",
    )
    created = service.create_gateway_application(payload)
    assert created.display_name == "claims-upload-service"
    try:
        service.create_gateway_application(payload)
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "gateway_application_conflict"
    else:
        raise AssertionError("expected gateway application conflict")


def test_create_gateway_application_rejects_unknown_grant_action() -> None:
    service = build_service()
    try:
        service.create_gateway_application(
            GatewayApplicationCreate(
                application_id="claims-upload-service",
                display_name="Claims Upload Service",
                grants=[GatewayApplicationGrant(actions=["discover", "delete_everything"])],
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail["code"] == "invalid_gateway_application_grant_actions"
    else:
        raise AssertionError("expected invalid grant action")


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
