import asyncio
import base64
import httpx
import hashlib
import json
from urllib.parse import quote

from starlette.responses import StreamingResponse

from connectors.framework.dsx_connector import DSXConnector
from connectors.jira.config import JiraConnectorConfig
from connectors.jira.jira_client import JiraClient
from connectors.jira.version import CONNECTOR_VERSION
from connectors.jira.monitor import Checkpoints, JiraMonitor
from shared.dsx_logging import dsx_logging
from shared.file_ops import relpath_matches_filter
from shared.models.connector_models import (
    AssetDiscoveryItem, AssetDiscoveryResponse, ObjectListingItem, ObjectListingResponse,
    ItemActionEnum, ScanRequestModel,
)
from shared.models.status_responses import ItemActionStatusResponse, StatusResponse, StatusResponseEnum

config = JiraConnectorConfig()
config.capabilities['monitor'] = config.monitor
config.capabilities['events'] = config.monitor
connector = DSXConnector(config)
client = JiraClient(config)
_monitor_task = None


async def monitor_loop():
    state = Checkpoints(config.jira_checkpoint_file)
    try:
        async with httpx.AsyncClient(timeout=30, verify=config.ca_bundle or config.verify_tls) as api:
            async def call(method, path, payload=None):
                headers = {"X-Enrollment-Token": connector._enrollment_token} if connector._enrollment_token else None
                response = await api.request(method, connector.dsx_connect_v2_url + '/api/v1/' + path,
                                             json=payload, headers=headers)
                response.raise_for_status()
                return response.json()

            async def submit(payload):
                await call('POST', 'execution/jobs/batch', payload)

            monitor = JiraMonitor(client, state, include, submit)
            while True:
                integration_id = connector._ng_registered_integration_id
                try:
                    if integration_id:
                        integration = await call('GET', 'control-plane/integrations/' + integration_id)
                        if integration.get('enabled'):
                            scopes = await call('GET', 'control-plane/scopes?integration_id=' + integration_id)
                            # Prefer space-level scopes when an issue is protected twice.
                            scopes.sort(key=lambda s: (not s['resource_selector'].lower().startswith('project'), s['scope_id']))
                            for scope in scopes:
                                if scope.get('enabled') and scope['integration_id'] == integration_id:
                                    result = await monitor.poll_scope(integration_id, scope)
                                    if result['baseline'] or result['submitted']:
                                        dsx_logging.info('Jira monitor scope %s: baseline=%s submitted=%s',
                                                         scope['scope_id'], result['baseline'], result['submitted'])
                except Exception as exc:
                    dsx_logging.warning('Jira monitor poll failed; retrying next interval: %s', exc)
                await asyncio.sleep(config.jira_poll_interval_seconds)
    finally:
        state.close()


def include(attachment):
    return not config.filter or relpath_matches_filter(attachment['filename'], config.filter)


@connector.startup
async def startup(base):
    global _monitor_task
    if config.monitor:
        _monitor_task = asyncio.create_task(monitor_loop(), name="jira-monitor")
    base.meta_info = f"Jira Cloud attachments {CONNECTOR_VERSION}; JQL: {config.asset}"
    return base


@connector.shutdown
async def shutdown():
    if _monitor_task:
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
    await client.close()


@connector.repo_check
async def repo_check():
    try:
        await client.page(config.asset or config.demo_jql())
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Jira search access verified")
    except Exception as exc:
        return StatusResponse(status=StatusResponseEnum.ERROR, message=str(exc))


@connector.full_scan
async def full_scan():
    queued = 0
    try:
        async for issue_key, attachment in client.attachments(config.asset or config.demo_jql()):
            if not include(attachment):
                continue
            result = await connector.scan_file_request(ScanRequestModel(
                location=str(attachment['id']), metainfo=f"{issue_key}/{attachment['filename']}",
                size_in_bytes=attachment.get('size'),
            ))
            if result.status != StatusResponseEnum.SUCCESS:
                raise RuntimeError(f"Enqueue stopped after {queued} attachments: {result.message}")
            queued += 1
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message=f"Queued {queued} Jira attachments")
    except Exception as exc:
        return StatusResponse(status=StatusResponseEnum.ERROR, message=str(exc))


@connector.preview
async def preview(limit: int):
    output = []
    async for key, attachment in client.attachments(config.asset or config.demo_jql()):
        if include(attachment):
            output.append(f"{key}/{attachment['filename']}")
        if len(output) >= max(1, min(limit, 25)):
            break
    return output


@connector.asset_discovery
async def asset_discovery(
    asset_type: str = "jira_jql", source: str = "configured_asset",
    limit: int = 100, cursor: str | None = None,
    asset_filter_mode: str | None = None, asset_filter_value: str | None = None,
):
    if config.jira_discover_spaces:
        try:
            spaces, next_cursor = await client.project_page(limit, cursor)
            assets = []
            value = (asset_filter_value or "").strip().casefold()
            for space in spaces:
                key = space['key']
                selected = [k for k in config.jira_demo_issue_keys if k.rsplit('-', 1)[0] == key]
                label = f"{space['name']} ({key})"
                if config.jira_demo_mode:
                    label += f" — Selected issues: {', '.join(selected)}" if selected else " — Demo scans disabled"
                match_text = f"{space['name']} ({key})".casefold()
                if value:
                    mode = (asset_filter_mode or 'contains').replace('-', '_')
                    matches = match_text.startswith(value) if mode in ('begins_with', 'starts_with', 'prefix') else match_text.endswith(value) if mode in ('ends_with', 'suffix') else value in match_text
                    if not matches:
                        continue
                assets.append(AssetDiscoveryItem(
                    id=key, display_name=label, selector=f'project = "{key}"',
                    metadata={"provider": "jira", "scope_type": "identity", "space_key": key,
                              "demo_mode": config.jira_demo_mode, "allowed_issue_keys": selected,
                              "demo_scans_enabled": bool(selected) if config.jira_demo_mode else True},
                ))
            return AssetDiscoveryResponse(asset_type="jira_space", source="project_search", assets=assets, next_cursor=next_cursor)
        except Exception as exc:
            return AssetDiscoveryResponse(asset_type="jira_space", status="error", message=str(exc))
    if config.jira_demo_mode:
        if cursor:
            return AssetDiscoveryResponse(asset_type="jira_space", assets=[])
        try:
            spaces = await client.demo_spaces()
            value = (asset_filter_value or "").strip().casefold()
            assets = []
            for space in spaces:
                key = space['key']
                selected = [k for k in config.jira_demo_issue_keys if k.rsplit('-', 1)[0] == key]
                label = f"{space['name']} ({key}) — Selected issues: {', '.join(selected)}"
                if value and value not in label.casefold():
                    continue
                assets.append(AssetDiscoveryItem(
                    id=key, display_name=label, selector=f'project = "{key}"',
                    metadata={"provider": "jira", "scope_type": "identity", "space_key": key,
                              "demo_mode": True, "allowed_issue_keys": selected,
                              "effective_jql": f'(project = "{key}") AND ({config.demo_jql()})'},
                ))
            return AssetDiscoveryResponse(asset_type="jira_space", source="demo_issue_projects", assets=assets)
        except Exception as exc:
            return AssetDiscoveryResponse(asset_type="jira_space", status="error", message=str(exc))
    # Expose only the explicitly configured JQL outside demo mode.
    assets = []
    if config.asset and not cursor:
        value = (asset_filter_value or "").strip().casefold()
        selector = config.asset.casefold()
        matches = not value or (selector == value if asset_filter_mode == "exact" else value in selector)
        if matches:
            assets.append(AssetDiscoveryItem(
                id=config.asset, display_name=config.asset, selector=config.asset,
                metadata={"provider": "jira", "scope_type": "identity"},
            ))
    return AssetDiscoveryResponse(asset_type="jira_jql", source="configured_asset", assets=assets)


@connector.object_listing
async def object_listing(scope: str = "", limit: int = 1000, cursor: str | None = None):
    jql = scope.strip() or config.asset or config.demo_jql()
    if config.asset and jql != config.asset:
        jql = f"({config.asset}) AND ({jql})"
    try:
        upstream_cursor = None
        offset = 0
        scope_hash = hashlib.sha256(jql.encode()).hexdigest()
        if cursor:
            state = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if state['scope'] != scope_hash:
                raise ValueError("Cursor belongs to another JQL scope")
            upstream_cursor, offset = state['page'], int(state['offset'])
            if offset < 0:
                raise ValueError("Invalid cursor offset")
        issues, next_cursor = await client.page(jql, upstream_cursor)
        objects = []
        for issue in issues:
            for attachment in issue.get('fields', {}).get('attachment', []):
                if include(attachment):
                    objects.append(ObjectListingItem(
                        identity=f"jira://{client.cloud_id}/attachment/{attachment['id']}",
                        location=str(attachment['id']), display_name=attachment['filename'],
                        size_in_bytes=attachment.get('size'),
                        metadata={'issue_key': issue['key'], 'filename': attachment['filename']},
                    ))
        page_limit = max(1, min(limit, 1000))
        remaining = objects[offset:]
        if len(remaining) > page_limit:
            state = {'scope': scope_hash, 'page': upstream_cursor, 'offset': offset + page_limit}
        elif next_cursor:
            state = {'scope': scope_hash, 'page': next_cursor, 'offset': 0}
        else:
            state = None
        encoded = base64.urlsafe_b64encode(json.dumps(state).encode()).decode() if state else None
        return ObjectListingResponse(scope=scope or config.asset, objects=remaining[:page_limit], next_cursor=encoded)
    except Exception as exc:
        return ObjectListingResponse(scope=scope or config.asset, status="error", message=str(exc))


@connector.read_file
async def read_file(request: ScanRequestModel):
    try:
        # Open before returning headers so authentication/permission errors are reported correctly.
        response = await client.open_attachment(request.location)
    except Exception as exc:
        return StatusResponse(status=StatusResponseEnum.ERROR, message=str(exc))

    async def chunks():
        try:
            async for chunk in response.aiter_bytes(65536):
                yield chunk
        finally:
            await response.aclose()

    filename = response.extensions.get('jira_filename') or request.metainfo.rsplit('/', 1)[-1]
    return StreamingResponse(chunks(), media_type="application/octet-stream", headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
    })


@connector.item_action
async def item_action(request: ScanRequestModel):
    return ItemActionStatusResponse(status=StatusResponseEnum.NOTHING,
                                   item_action=ItemActionEnum.NOT_IMPLEMENTED,
                                   message="Jira prototype is read-only")
