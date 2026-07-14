from dsx_connect_ng.jobs.models import JobCreate, JobItemCreate, StageRecord
from dsx_connect_ng.jobs.repository import InMemoryJobRepository


def test_inmemory_job_repository_crud_and_filtering() -> None:
    repo = InMemoryJobRepository()
    created = repo.create_job(
        JobCreate(
            job_type="scan.requested",
            state="accepted",
            integration_id="integration-a",
            payload={"path": "/finance/a.pdf"},
        )
    )
    assert repo.get_job(created.job_id) is not None

    updated = repo.update_job_state(created.job_id, state="queued", error=None)
    assert updated is not None
    assert updated.state == "queued"

    rows = repo.list_jobs(integration_id="integration-a", state="queued")
    assert len(rows) == 1
    assert rows[0].job_id == created.job_id


def test_inmemory_job_repository_outbox_lifecycle() -> None:
    repo = InMemoryJobRepository()
    job = repo.create_job(
        JobCreate(
            job_type="scan.requested",
            state="accepted",
        )
    )
    outbox = repo.create_outbox_record(
        job=job,
        topic=job.job_type,
        payload=job.as_envelope(state_override="queued").model_dump(mode="json"),
    )
    assert outbox.publish_state == "pending"

    claimed = repo.claim_outbox_record(outbox.outbox_id)
    assert claimed is not None
    assert claimed.publish_state == "publishing"
    assert repo.claim_outbox_record(outbox.outbox_id) is None

    published = repo.mark_outbox_published(outbox.outbox_id)
    assert published is not None
    assert published.publish_state == "published"
    assert published.publish_attempts == 1


def test_inmemory_job_repository_lists_pending_outbox() -> None:
    repo = InMemoryJobRepository()
    job = repo.create_job(JobCreate(job_type="scan.requested", state="accepted"))
    outbox = repo.create_outbox_record(
        job=job,
        topic=job.job_type,
        payload=job.as_envelope(state_override="queued").model_dump(mode="json"),
    )

    rows = repo.list_outbox_records(publish_state="pending")
    assert len(rows) == 1
    assert rows[0].outbox_id == outbox.outbox_id
    fetched = repo.get_outbox_record(outbox.outbox_id)
    assert fetched is not None
    assert fetched.topic == "scan.requested"


def test_inmemory_job_repository_job_items_and_summary() -> None:
    repo = InMemoryJobRepository()
    job = repo.create_job(JobCreate(job_type="scan.batch", state="accepted"))
    first = repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=0,
            object_identity="/finance/a.pdf",
            state="accepted",
        )
    )
    second = repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=1,
            object_identity="/finance/b.pdf",
            state="queued",
        )
    )

    repo.update_job_item_state(first.job_item_id, state="publish_pending", error={"code": "x"})
    items = repo.list_job_items(job_id=job.job_id)
    assert [item.item_index for item in items] == [0, 1]
    assert repo.get_job_item(second.job_item_id) is not None

    summary = repo.summarize_job_items(job.job_id)
    assert summary.total == 2
    assert summary.publish_pending == 1
    assert summary.queued == 1


def test_inmemory_job_repository_updates_stage_record() -> None:
    repo = InMemoryJobRepository()
    job = repo.create_job(JobCreate(job_type="scan.batch", state="accepted"))
    item = repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=0,
            object_identity="/finance/a.pdf",
            state="queued",
        )
    )

    updated = repo.update_job_item_stage(
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


def test_inmemory_job_repository_does_not_regress_terminal_stage_to_running() -> None:
    repo = InMemoryJobRepository()
    job = repo.create_job(JobCreate(job_type="scan.batch", state="accepted"))
    item = repo.create_job_item(
        JobItemCreate(
            job_id=job.job_id,
            item_index=0,
            object_identity="/finance/a.pdf",
            state="scanned",
            policy_stage=StageRecord(state="completed", result={"policy": "allow"}),
        )
    )

    updated = repo.update_job_item_stage(
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
