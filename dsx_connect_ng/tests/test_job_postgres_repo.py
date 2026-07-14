import os
import uuid

import pytest

from dsx_connect_ng.jobs.models import JobCreate, JobItemCreate, StageRecord, utcnow
psycopg = pytest.importorskip("psycopg")
from dsx_connect_ng.jobs.postgres_repo import PostgresJobRepository, apply_schema


TEST_POSTGRES_URL = os.environ.get("DSX_CONNECT_NG_TEST_POSTGRES_URL")


pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason="set DSX_CONNECT_NG_TEST_POSTGRES_URL to run postgres repository tests",
)


@pytest.fixture()
def postgres_repo():
    assert TEST_POSTGRES_URL
    apply_schema(TEST_POSTGRES_URL)
    return PostgresJobRepository(TEST_POSTGRES_URL)


def test_postgres_job_repository_crud(postgres_repo: PostgresJobRepository) -> None:
    suffix = uuid.uuid4().hex
    created = postgres_repo.create_job(
        JobCreate(
            job_type="scan.requested",
            state="accepted",
            idempotency_key=f"idem-{suffix}",
            payload={"selector": f"/finance/{suffix}.pdf"},
        )
    )
    fetched = postgres_repo.get_job(created.job_id)
    assert fetched is not None
    assert fetched.idempotency_key == f"idem-{suffix}"

    updated = postgres_repo.update_job_state(created.job_id, state="queued", error=None)
    assert updated is not None
    assert updated.state == "queued"


def test_postgres_job_repository_outbox(postgres_repo: PostgresJobRepository) -> None:
    suffix = uuid.uuid4().hex
    job = postgres_repo.create_job(
        JobCreate(
            job_type="scan.requested",
            state="accepted",
            idempotency_key=f"idem-outbox-{suffix}",
        )
    )
    outbox = postgres_repo.create_outbox_record(
        job=job,
        topic=job.job_type,
        payload=job.as_envelope(state_override="queued").model_dump(mode="json"),
    )
    assert outbox.publish_state == "pending"

    claimed = postgres_repo.claim_outbox_record(outbox.outbox_id)
    assert claimed is not None
    assert claimed.publish_state == "publishing"
    assert postgres_repo.claim_outbox_record(outbox.outbox_id) is None

    published = postgres_repo.mark_outbox_published(outbox.outbox_id)
    assert published is not None
    assert published.publish_state == "published"


def test_postgres_job_repository_lists_outbox(postgres_repo: PostgresJobRepository) -> None:
    suffix = uuid.uuid4().hex
    job = postgres_repo.create_job(
        JobCreate(
            job_type="scan.requested",
            state="accepted",
            idempotency_key=f"idem-list-{suffix}",
        )
    )
    outbox = postgres_repo.create_outbox_record(
        job=job,
        topic=job.job_type,
        payload=job.as_envelope(state_override="queued").model_dump(mode="json"),
    )

    rows = postgres_repo.list_outbox_records(publish_state="pending", limit=10)
    assert any(row.outbox_id == outbox.outbox_id for row in rows)
    fetched = postgres_repo.get_outbox_record(outbox.outbox_id)
    assert fetched is not None
    assert fetched.job_id == job.job_id


def test_postgres_job_repository_job_items(postgres_repo: PostgresJobRepository) -> None:
    suffix = uuid.uuid4().hex
    job = postgres_repo.create_job(
        JobCreate(
            job_type="scan.batch",
            state="accepted",
            idempotency_key=f"idem-items-{suffix}",
        )
    )
    first = postgres_repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=0,
            object_identity=f"/finance/{suffix}-a.pdf",
            state="accepted",
        )
    )
    postgres_repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=1,
            object_identity=f"/finance/{suffix}-b.pdf",
            state="queued",
        )
    )
    postgres_repo.update_job_item_state(first.job_item_id, state="publish_pending", error={"code": "x"})

    rows = postgres_repo.list_job_items(job_id=job.job_id)
    assert len(rows) == 2
    summary = postgres_repo.summarize_job_items(job.job_id)
    assert summary.total == 2
    assert summary.publish_pending == 1
    assert summary.queued == 1


def test_postgres_job_repository_updates_stage(postgres_repo: PostgresJobRepository) -> None:
    suffix = uuid.uuid4().hex
    job = postgres_repo.create_job(
        JobCreate(
            job_type="scan.batch",
            state="accepted",
            idempotency_key=f"idem-stage-{suffix}",
        )
    )
    item = postgres_repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=0,
            object_identity=f"/finance/{suffix}.pdf",
            state="queued",
        )
    )
    updated = postgres_repo.update_job_item_stage(
        item.job_item_id,
        stage_name="scan_stage",
        stage_record=StageRecord(state="running"),
        state="scanning",
        error=None,
        completed_at=None,
    )
    assert updated is not None
    assert updated.scan_stage.state == "running"
    assert updated.state == "scanning"


def test_postgres_job_repository_does_not_regress_terminal_stage_to_running(postgres_repo: PostgresJobRepository) -> None:
    suffix = uuid.uuid4().hex
    job = postgres_repo.create_job(
        JobCreate(
            job_type="scan.batch",
            state="accepted",
            idempotency_key=f"idem-stage-regression-{suffix}",
        )
    )
    item = postgres_repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=0,
            object_identity=f"/finance/{suffix}.pdf",
            state="scanned",
            policy_stage=StageRecord(state="completed", result={"policy": "allow"}),
        )
    )
    updated = postgres_repo.update_job_item_stage(
        item.job_item_id,
        stage_name="policy_stage",
        stage_record=StageRecord(state="running"),
        state="scanned",
        error=None,
        completed_at=None,
    )
    assert updated is not None
    assert updated.policy_stage.state == "completed"
    assert updated.policy_stage.result == {"policy": "allow"}


def test_postgres_job_repository_bulk_updates_stages(postgres_repo: PostgresJobRepository) -> None:
    suffix = uuid.uuid4().hex
    job = postgres_repo.create_job(
        JobCreate(
            job_type="scan.batch",
            state="accepted",
            idempotency_key=f"idem-bulk-stage-{suffix}",
        )
    )
    first = postgres_repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=0,
            object_identity=f"/finance/{suffix}-a.pdf",
            state="publish_pending",
        )
    )
    second = postgres_repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=1,
            object_identity=f"/finance/{suffix}-b.pdf",
            state="publish_pending",
        )
    )
    completed_at = utcnow()

    updated_count = postgres_repo.update_job_items_stages_bulk(
        [
            {
                "job_id": job.job_id,
                "job_item_id": first.job_item_id,
                "stage_records": {
                    "scan_stage": StageRecord(state="completed", result={"scanGuid": "scan-1"}),
                    "policy_stage": StageRecord(state="skipped"),
                    "remediation_stage": StageRecord(state="skipped"),
                    "delivery_stage": StageRecord(state="skipped"),
                    "dianna_stage": StageRecord(state="skipped"),
                },
                "state": "completed",
                "error": None,
                "completed_at": completed_at,
            },
            {
                "job_id": job.job_id,
                "job_item_id": second.job_item_id,
                "stage_records": {
                    "scan_stage": StageRecord(state="completed", result={"scanGuid": "scan-2"}),
                    "policy_stage": StageRecord(state="skipped"),
                    "remediation_stage": StageRecord(state="skipped"),
                    "delivery_stage": StageRecord(state="skipped"),
                    "dianna_stage": StageRecord(state="skipped"),
                },
                "state": "completed",
                "error": None,
                "completed_at": completed_at,
            },
        ]
    )

    rows = postgres_repo.list_job_items(job_id=job.job_id)
    assert updated_count == 2
    assert {row.state for row in rows} == {"completed"}
    assert {row.scan_stage.result["scanGuid"] for row in rows} == {"scan-1", "scan-2"}
    assert all(row.completed_at is not None for row in rows)
