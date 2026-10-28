from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

import httpx

from connectors.jira.config import JiraConnectorConfig


class JiraClient:
    """Scoped-token Jira Cloud client. Never follows attachment-supplied URLs."""

    def __init__(self, config: JiraConnectorConfig, *, transport=None):
        self.config = config
        self.http = httpx.AsyncClient(
            timeout=config.jira_http_timeout, follow_redirects=False,
            verify=config.ca_bundle or config.verify_tls, transport=transport,
        )
        self.cloud_id = config.jira_cloud_id

    async def close(self):
        await self.http.aclose()

    async def ready(self):
        if not self.config.jira_email or not self.config.token():
            raise ValueError("Jira email and API token are required")
        if not self.cloud_id:
            site = urlparse(self.config.jira_site_url)
            if site.scheme != "https" or not (site.hostname or "").endswith(".atlassian.net") or site.username or site.password or site.port:
                raise ValueError("jira_site_url must be an HTTPS *.atlassian.net site")
            response = await self.http.get(f"https://{site.hostname}/_edge/tenant_info")
            response.raise_for_status()
            self.cloud_id = response.json()["cloudId"]
        if not re.fullmatch(r"[A-Za-z0-9-]+", self.cloud_id):
            raise ValueError("Invalid Jira cloud ID")

    async def request(self, path, *, params=None, stream=False):
        await self.ready()
        url = f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/api/3/{path}"
        for attempt in range(4):
            req = self.http.build_request("GET", url, params=params)
            response = await self.http.send(req, auth=httpx.BasicAuth(self.config.jira_email, self.config.token()), stream=stream)
            if response.status_code in (429, 502, 503, 504) and attempt < 3:
                retry = response.headers.get("Retry-After", "")
                await response.aclose()
                await asyncio.sleep(min(float(retry), 60) if retry.isdigit() else 2 ** attempt)
                continue
            if response.status_code >= 300:
                code = response.status_code
                await response.aclose()
                raise RuntimeError(f"Jira HTTP {code}; check token scopes and project permissions")
            return response

    async def page(self, jql: str, cursor=None, *, fields="attachment"):
        if not jql.strip():
            raise ValueError("Configure an explicit JQL asset scope")
        restriction = self.config.demo_jql()
        if restriction:
            jql = f"({jql}) AND ({restriction})"
        params = {"jql": jql, "fields": fields, "maxResults": self.config.jira_page_size}
        if cursor:
            params["nextPageToken"] = cursor
        response = await self.request("search/jql", params=params)
        data = response.json()
        issues = data.get("issues", [])
        if self.config.jira_demo_mode:
            issues = [i for i in issues if i.get("key") in self.config.jira_demo_issue_keys]
        return issues, (None if data.get("isLast") else data.get("nextPageToken"))

    async def attachments(self, jql: str):
        cursor = None
        seen_pages = set()
        seen_attachments = set()
        while True:
            issues, next_cursor = await self.page(jql, cursor)
            for issue in issues:
                for attachment in issue.get("fields", {}).get("attachment", []):
                    aid = str(attachment["id"])
                    if aid not in seen_attachments:
                        seen_attachments.add(aid)
                        yield issue["key"], attachment
            if not next_cursor:
                return
            if next_cursor in seen_pages:
                raise RuntimeError("Jira returned a repeated pagination cursor")
            seen_pages.add(next_cursor)
            cursor = next_cursor

    async def open_attachment(self, attachment_id: str):
        if not re.fullmatch(r"[0-9]+", attachment_id):
            raise ValueError("Attachment location must be a numeric Jira attachment ID")
        filename = None
        if self.config.jira_demo_mode:
            async for _, attachment in self.attachments(self.config.asset or self.config.demo_jql()):
                if str(attachment['id']) == attachment_id:
                    filename = attachment['filename']
                    break
            if filename is None:
                raise ValueError("Attachment is outside the demo issue allowlist")
        response = await self.request(f"attachment/content/{attachment_id}", params={"redirect": "false"}, stream=True)
        if filename:
            response.extensions['jira_filename'] = filename
        return response

    async def demo_spaces(self):
        """Read actual project metadata only from allowlisted issues, not the entire tenant."""
        cursor = None
        seen = set()
        spaces = {}
        while True:
            issues, next_cursor = await self.page(self.config.demo_jql(), cursor, fields="project")
            for issue in issues:
                project = issue.get('fields', {}).get('project') or {}
                key = project.get('key')
                if key:
                    spaces[key] = {'key': key, 'name': project.get('name') or key}
            if not next_cursor:
                return list(spaces.values())
            if next_cursor in seen:
                raise RuntimeError("Jira returned a repeated pagination cursor")
            seen.add(next_cursor)
            cursor = next_cursor


    async def project_page(self, limit=100, cursor=None):
        start = int(cursor or 0)
        if start < 0:
            raise ValueError("Invalid space cursor")
        response = await self.request('project/search', params={
            'startAt': start, 'maxResults': max(1, min(limit, 100)), 'orderBy': 'name',
        })
        data = response.json()
        values = data.get('values', [])
        next_start = start + len(values)
        next_cursor = str(next_start) if values and not data.get('isLast') and next_start < data.get('total', next_start) else None
        return values, next_cursor
