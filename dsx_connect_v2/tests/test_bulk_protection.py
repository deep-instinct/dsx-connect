from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from dsx_connect_v2.app import create_app
from dsx_connect_v2.config import settings
from dsx_connect_v2.control_plane.models import IntegrationCreate, ProtectedScopeCreate, ProtectedScopeUpdate
from dsx_connect_v2.control_plane import bulk_protection


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(settings, "control_plane_backend", "memory")
    monkeypatch.setattr(settings, "job_bus_backend", "memory")
    app = create_app()
    cp = app.state.control_plane_service
    cp.create_integration(IntegrationCreate(integration_id="gcs", platform="gcs", platform_key="test", display_name="GCS"))
    return app, cp, TestClient(app)


def request(selectors, **kwargs):
    return {"targets": [{"integration_id": "gcs", "selector": s} for s in selectors],
            "policy": {"policy_id": "new", "display_name": "Detect only"}, **kwargs}


def scope(cp, selector, **kwargs):
    return cp.create_scope(ProtectedScopeCreate(
        integration_id="gcs", scope_type="path", resource_selector=selector,
        display_name=selector, mode="full_scan", **kwargs))


def plan(client, body):
    r = client.post('/api/v1/ui/assets/bulk-protection/preview', json=body)
    assert r.status_code == 200, r.text
    return r.json()


def apply(client, operation):
    r = client.post(f"/api/v1/ui/assets/bulk-protection/{operation['operation_id']}/apply")
    assert r.status_code == 202, r.text
    return client.get(f"/api/v1/ui/assets/bulk-protection/{operation['operation_id']}?include_outcomes=true").json()


def test_review_is_non_mutating_preserves_existing_and_never_scans(env):
    app, cp, client = env
    original = scope(cp, 'protected', post_scan_policy={"policy_id": "original"})
    operation = plan(client, request(['new', 'protected', 'new']))
    assert operation['total'] == 2
    assert operation['review']['new'] == 1
    assert operation['review']['skip'] == 1
    assert len(cp.list_scopes()) == 1
    result = apply(client, operation)
    assert result['state'] == 'completed'
    assert result['progress'] == {'completed': 1, 'skipped': 1, 'failed': 0, 'pending': 0}
    assert cp.get_scope_or_404(original.scope_id).post_scan_policy['policy_id'] == 'original'
    jobs = app.state.job_service.repo.list_jobs()
    assert all(j.job_type == 'protection.bulk' for j in jobs)
    assert client.get('/api/v1/ui/scan-results').json()['results'] == []
    assert app.state.job_service.repo.list_outbox_records() == []
    assert client.post(f"/api/v1/ui/assets/bulk-protection/{operation['operation_id']}/apply").status_code == 409


def test_replace_and_resume_preserve_scanner_binding(env):
    _, cp, client = env
    active = scope(cp, 'active', post_scan_policy={"policy_id": "old", "scanner": {"protected_entity": 42}})
    disabled = scope(cp, 'disabled', enabled=False, post_scan_policy={"policy_id": "old"})
    operation = plan(client, request(['active', 'disabled'], replace_existing=True))
    assert operation['review']['replace'] == 1
    assert operation['review']['resume'] == 1
    assert apply(client, operation)['progress']['completed'] == 2
    assert cp.get_scope_or_404(active.scope_id).post_scan_policy['scanner']['protected_entity'] == 42
    assert cp.get_scope_or_404(disabled.scope_id).enabled


def test_changes_after_review_fail_individually_without_overwriting(env):
    _, cp, client = env
    original = scope(cp, 'changed', post_scan_policy={"policy_id": "old"})
    operation = plan(client, request(['changed', 'new'], replace_existing=True))
    cp.update_scope(original.scope_id, ProtectedScopeUpdate(post_scan_policy={"policy_id": "operator-edit"}))
    result = apply(client, operation)
    assert result['state'] == 'failed'
    assert result['progress']['failed'] == 1
    assert result['progress']['completed'] == 1
    assert cp.get_scope_or_404(original.scope_id).post_scan_policy['policy_id'] == 'operator-edit'
    assert 'changed after review' in result['outcomes'][0]['error']['message']


def test_disable_skips_unprotected_and_broader_scopes(env):
    _, cp, client = env
    root = scope(cp, 'bucket', post_scan_policy={"policy_id": "keep"})
    operation = plan(client, request(['bucket', 'bucket/child', 'missing'], action='disable'))
    assert operation['review']['disable'] == 1
    assert operation['review']['skip'] == 2
    apply(client, operation)
    current = cp.get_scope_or_404(root.scope_id)
    assert not current.enabled
    assert current.post_scan_policy['policy_id'] == 'keep'


def test_all_matching_crosses_pages_filters_then_freezes_selection(env, monkeypatch):
    from dsx_connect_v2.api.routes import ui
    _, cp, client = env
    calls = []
    def listing(*args, **kwargs):
        calls.append(kwargs['cursor'])
        if kwargs['cursor'] is None:
            return {'status': 'success', 'asset_type': 'bucket', 'assets': [
                {'id': f'bucket-{i}', 'selector': f'bucket-{i}', 'display_name': f'bucket-{i}'} for i in range(1000)], 'next_cursor':'page-2'}
        return {'status':'success','asset_type':'bucket','assets':[{'id':'bucket-last','selector':'bucket-last'}]}
    monkeypatch.setattr(ui, '_fetch_connector_assets', listing)
    operation = plan(client, {'all_matching':True,'integration_id':'gcs','policy':{'policy_id':'new'}})
    assert operation['total'] == 1001
    assert calls == [None, 'page-2']
    assert cp.list_scopes() == []
    # Applying must use the persisted selection, never enumerate again.
    monkeypatch.setattr(ui, '_fetch_connector_assets', lambda *a, **kw: pytest.fail('Must not rediscover after confirmation'))
    result = apply(client, operation)
    assert result['progress']['completed'] == 1001
    assert len(cp.list_scopes()) == 1001
    assert len(result['outcomes']) == 1001


def test_incomplete_discovery_is_rejected(env, monkeypatch):
    from dsx_connect_v2.api.routes import ui
    _, cp, client = env
    monkeypatch.setattr(ui, '_fetch_connector_assets', lambda *a, **kw: {'unsupported':True,'asset_type':'bucket','assets':[]})
    r = client.post('/api/v1/ui/assets/bulk-protection/preview', json={'all_matching':True,'integration_id':'gcs'})
    assert r.status_code == 409
    assert cp.list_scopes() == []


def test_atomic_claim_only_one_confirmation_wins(env):
    app, _, client = env
    operation = plan(client, request(['new']))
    repo = app.state.job_service.repo
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: repo.claim_protection_job(operation['operation_id'], 'planned', 'queued'), range(8)))
    assert results.count(True) == 1


def test_audit_survives_service_recreation_and_is_excluded_from_scan_metrics(env):
    app, _, client = env
    operation = plan(client, request(['new']))
    apply(client, operation)
    from dsx_connect_v2.jobs.service import JobService
    # Reading uses persisted repository records, not a process-local task registry.
    recreated = JobService(app.state.job_service.repo, app.state.job_service.bus)
    result = bulk_protection.describe(recreated, operation['operation_id'])
    assert result['progress']['completed'] == 1
    assert list(app.state.job_service.repo.dashboard_stages(result['created_at'])) == []
    assert client.get('/api/v1/ui/assets/bulk-protection').json()['operations'][0]['operation_id'] == operation['operation_id']


def test_concurrent_scope_edit_at_write_is_not_overwritten(env, monkeypatch):
    _, cp, client = env
    original_scope = scope(cp, 'race', post_scan_policy={'policy_id':'original'})
    operation = plan(client, request(['race'], replace_existing=True))
    original_update = cp.repo.update_scope
    def race(scope_id, payload, **kwargs):
        original_update(scope_id, ProtectedScopeUpdate(post_scan_policy={'policy_id':'concurrent'}))
        return original_update(scope_id, payload, **kwargs)
    monkeypatch.setattr(cp.repo, 'update_scope', race)
    result = apply(client, operation)
    assert result['progress']['failed'] == 1
    assert cp.get_scope_or_404(original_scope.scope_id).post_scan_policy['policy_id'] == 'concurrent'
