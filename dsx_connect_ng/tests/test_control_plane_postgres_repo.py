import os
import uuid

import pytest

from dsx_connect_ng.control_plane.models import (
    ConnectorInstanceHeartbeat,
    ConnectorInstanceRegister,
    IntegrationCreate,
    IntegrationUpdate,
    ProtectedScopeCreate,
)
psycopg = pytest.importorskip("psycopg")
from dsx_connect_ng.control_plane.postgres_repo import PostgresControlPlaneRepository, apply_schema


TEST_POSTGRES_URL = os.environ.get("DSX_CONNECT_NG_TEST_POSTGRES_URL")


pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason="set DSX_CONNECT_NG_TEST_POSTGRES_URL to run postgres repository tests",
)


@pytest.fixture()
def postgres_repo():
    assert TEST_POSTGRES_URL
    apply_schema(TEST_POSTGRES_URL)
    repo = PostgresControlPlaneRepository(TEST_POSTGRES_URL)
    return repo


def test_postgres_repository_integration_crud(postgres_repo: PostgresControlPlaneRepository) -> None:
    suffix = uuid.uuid4().hex
    created = postgres_repo.create_integration(
        IntegrationCreate(
            platform="sharepoint",
            platform_key=f"tenant-postgres-{suffix}",
            display_name="Tenant Postgres A",
        )
    )
    fetched = postgres_repo.get_integration(created.integration_id)
    assert fetched is not None
    assert fetched.platform_key == f"tenant-postgres-{suffix}"

    updated = postgres_repo.update_integration(
        created.integration_id,
        IntegrationUpdate(display_name="Tenant Postgres Updated", enabled=False),
    )
    assert updated is not None
    assert updated.display_name == "Tenant Postgres Updated"
    assert updated.enabled is False


def test_postgres_repository_scope_crud(postgres_repo: PostgresControlPlaneRepository) -> None:
    suffix = uuid.uuid4().hex
    integration = postgres_repo.create_integration(
        IntegrationCreate(
            platform="s3",
            platform_key=f"acct-postgres-{suffix}",
            display_name="Account Postgres A",
        )
    )
    scope = postgres_repo.create_scope(
        ProtectedScopeCreate(
            integration_id=integration.integration_id,
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance",
            mode="monitor",
        ),
        normalized_selector="/finance",
    )
    fetched = postgres_repo.get_scope(scope.scope_id)
    assert fetched is not None
    assert fetched.normalized_selector == "/finance"


def test_postgres_repository_connector_instance_crud(postgres_repo: PostgresControlPlaneRepository) -> None:
    suffix = uuid.uuid4().hex
    integration = postgres_repo.create_integration(
        IntegrationCreate(
            platform="gcs",
            platform_key=f"project-postgres-{suffix}",
            display_name="Project Postgres A",
        )
    )
    registered = postgres_repo.upsert_connector_instance(
        ConnectorInstanceRegister(
            connector_instance_id=f"gcs-postgres-{suffix}",
            integration_id=integration.integration_id,
            platform="gcs",
            platform_key=f"project-postgres-{suffix}",
            connector_name="google-cloud-storage-connector",
            connector_version="0.5.55",
            base_url="http://gcs:80",
            capabilities={"discover": True, "read": True},
            health="healthy",
        ),
        integration_id=integration.integration_id,
    )
    assert registered.integration_id == integration.integration_id

    heartbeat = postgres_repo.update_connector_instance_heartbeat(
        registered.connector_instance_id,
        ConnectorInstanceHeartbeat(health="degraded", labels={"pod": "gcs-postgres"}),
    )
    assert heartbeat is not None
    assert heartbeat.health == "degraded"
    assert heartbeat.labels == {"pod": "gcs-postgres"}
    assert len(postgres_repo.list_connector_instances(integration_id=integration.integration_id)) == 1
