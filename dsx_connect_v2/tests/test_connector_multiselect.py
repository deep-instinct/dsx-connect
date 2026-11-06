import json

import pytest
from fastapi.testclient import TestClient

from dsx_connect_v2.app import create_app
from dsx_connect_v2.config import settings
from dsx_connect_v2.control_plane.models import IntegrationCreate, ProtectedScopeCreate


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(settings, 'control_plane_backend', 'memory')
    monkeypatch.setattr(settings, 'job_bus_backend', 'memory')
    app = create_app()
    cp = app.state.control_plane_service
    for key in ['a', 'b', 'excluded']:
        cp.create_integration(IntegrationCreate(integration_id=key, platform='gcs', platform_key=key, display_name=key,
            config={'reader': {'default_strategy':'proxy','proxy':{'base_url':f'http://{key}','connector_name':'gcs'}}}))
    return app, cp, TestClient(app)


def listing(monkeypatch, datasets):
    from dsx_connect_v2.api.routes import ui
    calls = []
    def fetch(base, name, **kwargs):
        key = base.rstrip('/').split('//')[-1]
        calls.append((key, kwargs['cursor'], kwargs['limit']))
        start = int(kwargs['cursor'] or 0)
        names = datasets[key]
        end = start + kwargs['limit']
        return {'asset_type':'bucket','status':'success','assets':[{'id':n,'selector':n} for n in names[start:end]],
                'next_cursor':str(end) if end < len(names) else None}
    monkeypatch.setattr(ui, '_fetch_connector_assets', fetch)
    return calls


def test_multiple_connectors_paginate_without_duplicates_or_refetching_exhausted(env, monkeypatch):
    _, _, client = env
    calls = listing(monkeypatch, {'a':['a1','a2','a3'], 'b':['b1','b2']})
    cursors, seen = {}, []
    for _ in range(3):
        r = client.get('/api/v1/ui/assets/protected', params=[('integration_ids','a'),('integration_ids','b'),('limit',2),('cursors',json.dumps(cursors))])
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body['assets']) <= 2
        seen += [(asset['integration_id'],asset['selector']) for asset in body['assets']]
        cursors = body['next_cursors']
    assert seen == [('a','a1'),('a','a2'),('a','a3'),('b','b1'),('b','b2')]
    assert cursors == {'a':None,'b':None}
    assert calls == [('a',None,2),('a','2',2),('b',None,1),('b','1',2)]


def test_all_connectors_is_bounded_and_pending_connectors_continue_next_page(env, monkeypatch):
    _, _, client = env
    calls = listing(monkeypatch, {'a':['a1'], 'b':['b1'], 'excluded':['c1']})
    first = client.get('/api/v1/ui/assets/protected',params={'cursors':'{}','limit':1}).json()
    assert len(first['assets']) == 1
    assert calls == [('a',None,1)]
    second = client.get('/api/v1/ui/assets/protected',params={'cursors':json.dumps(first['next_cursors']),'limit':1}).json()
    assert second['assets'][0]['integration_id'] == 'b'
    assert calls == [('a',None,1),('b',None,1)]


@pytest.mark.parametrize('cursors',['[]','null','{"a":false}','invalid'])
def test_invalid_cursor_map_rejected(env,cursors):
    _, _, client = env
    assert client.get('/api/v1/ui/assets/protected',params={'cursors':cursors}).status_code == 422


def test_bulk_all_matching_across_selected_connectors_only(env, monkeypatch):
    _, cp, client = env
    calls = listing(monkeypatch, {'a':['a1','a2'], 'b':['b1']})
    r = client.post('/api/v1/ui/assets/bulk-protection/preview',json={
        'all_matching':True,'integration_ids':['a','b'],'policy':{'policy_id':'test'},
    })
    assert r.status_code == 200,r.text
    plan = r.json()
    assert plan['total'] == 3
    assert cp.list_scopes() == []
    result = client.post(f"/api/v1/ui/assets/bulk-protection/{plan['operation_id']}/apply")
    assert result.status_code == 202
    assert {(s.integration_id,s.resource_selector) for s in cp.list_scopes()} == {('a','a1'),('a','a2'),('b','b1')}
    assert all(key in ['a','b'] for key,_,_ in calls)


def test_scope_fallback_paginates_with_other_connectors(env, monkeypatch):
    from dsx_connect_v2.api.routes import ui
    _, cp, client = env
    for name in ['one','two','three']:
        cp.create_scope(ProtectedScopeCreate(integration_id='a',scope_type='path',resource_selector=name,display_name=name,mode='full_scan'))
    monkeypatch.setattr(ui,'_fetch_connector_assets',lambda *args,**kwargs:{'unsupported':True,'asset_type':'bucket','assets':[]})
    first=client.get('/api/v1/ui/assets/protected',params={'integration_ids':'a','cursors':'{}','limit':2}).json()
    assert len(first['assets']) == 2
    second=client.get('/api/v1/ui/assets/protected',params={'integration_ids':'a','cursors':json.dumps(first['next_cursors']),'limit':2}).json()
    assert len(second['assets']) == 1
    assert second['next_cursors'] == {'a':None}
    assert len({a['selector'] for a in first['assets']+second['assets']}) == 3


def test_cursor_for_removed_connector_does_not_leave_endless_next_page(env,monkeypatch):
    _, _, client = env
    calls=listing(monkeypatch, {'a':['a1']})
    result=client.get('/api/v1/ui/assets/protected',params={'integration_ids':'a','cursors':json.dumps({'a':None,'removed':'more'})}).json()
    assert result['next_cursors'] == {'a':None}
    assert result['assets'] == []
    assert calls == []
