from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from shared.dsx_logging import dsx_logging
from shared.graph.base import MSGraphClientBase
from shared.graph.drive import delta_changes, build_drive_item_path
from connectors.onedrive.config import OneDriveConnectorConfig


class OneDriveClient(MSGraphClientBase):
    """Microsoft Graph client for OneDrive (user drive) operations."""

    def __init__(self, cfg: OneDriveConnectorConfig):
        verify: httpx._types.VerifyTypes
        if not cfg.verify_tls:
            verify = False
        elif cfg.ca_bundle:
            verify = cfg.ca_bundle
        else:
            verify = True

        super().__init__(
            tenant_id=cfg.tenant_id,
            client_id=cfg.client_id,
            client_secret=cfg.client_secret,
            verify=verify,
        )
        self._cfg = cfg
        self._drive_id: Optional[str] = None
        self._drive_resource: Optional[str] = None

    async def _ensure_drive(self):
        if self._drive_resource:
            return
        user = self._cfg.user_id.strip()
        if not user:
            raise RuntimeError("OneDrive user_id is required")

        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        url = self.graph_url(f"users/{user}/drive")
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        self._drive_id = data.get("id")
        if not self._drive_id:
            raise RuntimeError("Unable to resolve OneDrive drive id")
        self._drive_resource = f"users/{user}/drive"
        dsx_logging.info(f"Resolved OneDrive drive id={self._drive_id} for user={user}")

    @property
    def drive_resource(self) -> str:
        if not self._drive_resource:
            raise RuntimeError("Drive not resolved")
        return self._drive_resource

    async def list_files(self, path: str = "") -> List[Dict[str, Any]]:
        await self._ensure_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        if path and path != "/":
            encoded = path.strip("/")
            url = self.graph_url(f"{self.drive_resource}/root:/{encoded}:/children?$select=id,name,folder,parentReference&$top=200")
        else:
            url = self.graph_url(f"{self.drive_resource}/root/children?$select=id,name,folder,parentReference&$top=200")
        items: List[Dict[str, Any]] = []
        while url:
            resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                detail = None
                try:
                    detail = resp.text
                except Exception:
                    pass
                raise RuntimeError(f"Graph list children failed: {resp.status_code} path={path} body={detail}")
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return items

    async def iter_files_recursive(self, path: str = "") -> AsyncIterator[Dict[str, Any]]:
        stack = [path.strip("/")]
        while stack:
            current = stack.pop()
            items = await self.list_files(current)
            for it in items:
                name = it.get("name")
                rel_path = (current + "/" + name).strip("/") if current else (name or "")
                if rel_path:
                    it = {**it, "path": rel_path}
                yield it
                if it.get("folder"):
                    stack.append(rel_path)

    async def delta_changes(self, cursor: Optional[str]) -> tuple[List[dict], Optional[str]]:
        await self._ensure_drive()
        page_size = max(1, int(getattr(self._cfg, "sp_graph_page_size", 200) or 200))
        return await delta_changes(self, self.drive_resource, cursor, page_size=page_size)

    async def iter_files_delta(self) -> AsyncIterator[Dict[str, Any]]:
        cursor: Optional[str] = None
        while True:
            items, cursor = await self.delta_changes(cursor)
            for item in items:
                yield item
            if not cursor:
                break

    async def download_file(self, identifier: str) -> httpx.Response:
        await self._ensure_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        if "/" in identifier or ":" in identifier:
            encoded = identifier.strip("/")
            url = self.graph_url(f"{self.drive_resource}/root:/{encoded}:/content")
        else:
            url = self.graph_url(f"{self.drive_resource}/items/{identifier}/content")
        resp = await client.get(url, headers=headers, follow_redirects=True)
        resp.raise_for_status()
        return resp

    async def upload_file(self, path: str, content: bytes) -> Dict[str, Any]:
        await self._ensure_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        encoded = path.strip("/")
        url = self.graph_url(f"{self.drive_resource}/root:/{encoded}:/content")
        resp = await client.put(url, headers=headers, content=content)
        resp.raise_for_status()
        return resp.json()

    async def get_item_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        url = self.graph_url(f"{self.drive_resource}/items/{item_id}?$select=id,name,parentReference,webUrl")
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def get_item_path(self, item_id: str) -> Optional[str]:
        item = await self.get_item_by_id(item_id)
        if not item:
            return None
        name = item.get("name") or ""
        return build_drive_item_path(item.get("parentReference") or {}, name)

    async def resolve_item_id(self, identifier: str) -> str:
        if "/" in identifier or ":" in identifier:
            item = await self._get_item_by_path(identifier)
            if not item:
                raise RuntimeError(f"Item not found for path: {identifier}")
            return item["id"]
        return identifier

    async def _get_item_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        await self._ensure_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        url = self.graph_url(f"{self.drive_resource}/root:/{path.strip('/')}")
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def ensure_folder(self, folder_path: str) -> Dict[str, Any]:
        folder_path = folder_path.strip("/")
        if not folder_path:
            root = await self._get_item_by_path("")
            if root:
                return root
        existing = await self._get_item_by_path(folder_path)
        if existing:
            return existing

        parts = [seg for seg in folder_path.split("/") if seg]
        current_path = ""
        parent_path = ""
        last_created: Optional[Dict[str, Any]] = None
        for seg in parts:
            current_path = f"{current_path}/{seg}".strip("/")
            item = await self._get_item_by_path(current_path)
            if item is None:
                last_created = await self._create_folder(parent_path, seg)
            parent_path = current_path
        item = await self._get_item_by_path(current_path)
        if item is None:
            if last_created is not None:
                return last_created
            raise RuntimeError(f"Failed to ensure folder: {folder_path}")
        return item

    async def _create_folder(self, parent_path: str, name: str) -> Dict[str, Any]:
        await self._ensure_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Content-Type": "application/json", "Accept": "application/json;odata.metadata=none"})
        payload = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"}
        if parent_path:
            url = self.graph_url(f"{self.drive_resource}/root:/{parent_path.strip('/')}:/children")
        else:
            url = self.graph_url(f"{self.drive_resource}/root/children")
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def move_file(
        self,
        identifier: str,
        dest_folder_path: str,
        new_name: Optional[str] = None,
        conflict_behavior: str = "rename",
    ) -> Dict[str, Any]:
        await self._ensure_drive()
        item_id = await self.resolve_item_id(identifier)
        dest_folder = await self.ensure_folder(dest_folder_path)
        parent_id = dest_folder["id"]
        payload: Dict[str, Any] = {"parentReference": {"id": parent_id}}
        if new_name:
            payload["name"] = new_name
        if conflict_behavior:
            payload["@microsoft.graph.conflictBehavior"] = conflict_behavior
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Content-Type": "application/json", "Accept": "application/json;odata.metadata=none"})
        url = self.graph_url(f"{self.drive_resource}/items/{item_id}")
        resp = await client.patch(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def delete_file(self, item_id: str) -> None:
        await self._ensure_drive()
        client = await self.get_client()
        headers = await self.auth_headers()
        url = self.graph_url(f"{self.drive_resource}/items/{item_id}")
        resp = await client.delete(url, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph delete failed: {resp.status_code}")

    async def test_connection(self) -> bool:
        try:
            await self._ensure_drive()
            await self.list_files("")
            return True
        except Exception as exc:
            dsx_logging.warning(f"OneDrive repo check failed: {exc}")
            return False
