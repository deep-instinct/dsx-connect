from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from shared.dsx_logging import dsx_logging
from shared.graph.base import MSGraphClientBase
from shared.graph.drive import build_drive_item_path, delta_changes
from connectors.sharepoint.config import SharepointConnectorConfig

SPO_API = "https://{host}/sites/{site}/_api"


class SharePointClient(MSGraphClientBase):
    """
    Microsoft Graph client for SharePoint drive operations.

    Handles site/drive discovery, delta enumeration, download/upload, and item actions.
    """

    def __init__(self, cfg: SharepointConnectorConfig):
        verify: httpx._types.VerifyTypes
        if not cfg.sp_verify_tls:
            verify = False
        elif cfg.sp_ca_bundle:
            verify = cfg.sp_ca_bundle
        else:
            verify = True

        super().__init__(
            tenant_id=cfg.sp_tenant_id,
            client_id=cfg.sp_client_id,
            client_secret=cfg.sp_client_secret,
            verify=verify,
            log_token_claims=cfg.sp_log_token_claims,
        )
        self._cfg = cfg
        self._site_id: Optional[str] = None
        self._drive_id: Optional[str] = None
        self._drive_resource: Optional[str] = None
        self._spo_scope = f"https://{cfg.sp_hostname}/.default" if cfg.sp_hostname else None
        self._digest_cache: dict[str, tuple[str, float]] = {}

    # ---------------------- discovery ----------------------
    async def _ensure_site_and_drive(self):
        if self._site_id and self._drive_id and self._drive_resource:
            return

        client = await self.get_client()
        headers = await self.auth_headers()

        rel_site_path = (self._cfg.sp_site_path or "").strip("/")
        if rel_site_path.lower().startswith("sites/"):
            rel_site_path = rel_site_path.split("/", 1)[1]
        site_url = self.graph_url(
            f"sites/{self._cfg.sp_hostname}:/sites/{rel_site_path}?$select=id,webUrl,displayName"
        )
        resp = await client.get(site_url, headers=headers)
        if resp.status_code >= 400:
            body = None
            try:
                body = resp.text
            except Exception:
                pass
            raise RuntimeError(
                f"Graph site lookup failed: {resp.status_code} host={self._cfg.sp_hostname} "
                f"site_path={rel_site_path} body={body}"
            )
        site = resp.json()
        self._site_id = site["id"]

        drive_name = (self._cfg.sp_drive_name or "").strip()
        if drive_name and ("/" in drive_name or "\\" in drive_name):
            dsx_logging.warning(
                f"sp_drive_name looks like a path ('{drive_name}'); ignoring override and using default drive."
            )
            drive_name = ""

        if drive_name:
            drives_url = self.graph_url(f"sites/{self._site_id}/drives")
            dresp = await client.get(drives_url, headers=headers)
            dresp.raise_for_status()
            drives = dresp.json().get("value", [])

            def _norm(value: Optional[str]) -> str:
                return (value or "").strip().lower().replace(" ", "")

            want = _norm(drive_name)
            match = next((d for d in drives if _norm(d.get("name")) == want), None)
            if not match and want in {"documents", "shareddocuments"}:
                match = next((d for d in drives if _norm(d.get("name")) in {"documents", "shareddocuments"}), None)
            if not match:
                raise RuntimeError(f"Drive named '{self._cfg.sp_drive_name}' not found on site.")
            self._drive_id = match["id"]
        else:
            ddef = await client.get(self.graph_url(f"sites/{self._site_id}/drive"), headers=headers)
            ddef.raise_for_status()
            self._drive_id = ddef.json()["id"]

        self._drive_resource = f"drives/{self._drive_id}"
        dsx_logging.info(f"Resolved SharePoint site={self._site_id}, drive={self._drive_id}")

    async def site_drive_ids(self) -> tuple[str, str]:
        await self._ensure_site_and_drive()
        if not self._site_id or not self._drive_id:
            raise RuntimeError("SharePoint site/drive not resolved")
        return self._site_id, self._drive_id

    @property
    def drive_resource(self) -> str:
        if not self._drive_resource:
            raise RuntimeError("Drive not resolved")
        return self._drive_resource

    # ---------------------- tokens ----------------------
    async def graph_token(self) -> str:
        """Expose Graph token for subscription helpers."""
        return await self.get_access_token()

    async def _headers_spo(self) -> Dict[str, str]:
        if not self._spo_scope:
            raise RuntimeError("sp_hostname is required for SharePoint REST calls")
        token = await self.get_access_token([self._spo_scope])
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json;odata=nometadata",
        }

    # ---------------------- drive operations ----------------------
    async def list_files(self, path: str = "") -> List[Dict[str, Any]]:
        await self._ensure_site_and_drive()
        client = await self.get_client()
        base_headers = await self.auth_headers()
        page_size = max(1, int(getattr(self._cfg, "sp_graph_page_size", 200) or 200))
        headers = {
            **base_headers,
            "Prefer": f"odata.maxpagesize={page_size}",
            "Accept": "application/json;odata.metadata=none",
        }
        if path and path != "/":
            encoded = unquote(path.strip("/"))
            url = self.graph_url(f"{self._drive_resource}/root:/{encoded}:/children?$select=id,name,folder,parentReference&$top=200")
        else:
            url = self.graph_url(f"{self._drive_resource}/root/children?$select=id,name,folder,parentReference&$top=200")
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

    async def iter_files_delta(self) -> AsyncIterator[Dict[str, Any]]:
        await self._ensure_site_and_drive()
        cursor: Optional[str] = None
        page_size = max(1, int(getattr(self._cfg, "sp_graph_page_size", 200) or 200))
        while True:
            items, cursor = await delta_changes(
                self,
                self._drive_resource,
                cursor,
                page_size=page_size,
            )
            for item in items:
                yield item
            if not cursor:
                break

    async def delta_changes(self, cursor: Optional[str]) -> tuple[List[dict], Optional[str]]:
        await self._ensure_site_and_drive()
        page_size = max(1, int(getattr(self._cfg, "sp_graph_page_size", 200) or 200))
        return await delta_changes(self, self._drive_resource, cursor, page_size=page_size)

    async def download_file(self, identifier: str) -> httpx.Response:
        await self._ensure_site_and_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        if "/" in identifier or ":" in identifier:
            encoded = identifier.strip("/")
            url = self.graph_url(f"{self._drive_resource}/root:/{encoded}:/content")
        else:
            url = self.graph_url(f"{self._drive_resource}/items/{identifier}/content")
        resp = await client.get(url, headers=headers, follow_redirects=True)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph download failed: {resp.status_code}")
        return resp

    async def upload_file(self, path: str, content: bytes) -> Dict[str, Any]:
        await self._ensure_site_and_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        encoded = path.strip("/")
        url = self.graph_url(f"{self._drive_resource}/root:/{encoded}:/content")
        resp = await client.put(url, headers=headers, content=content)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph upload failed: {resp.status_code}")
        return resp.json()

    async def get_item_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_site_and_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        url = self.graph_url(f"{self._drive_resource}/items/{item_id}?$select=id,name,parentReference,webUrl")
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
        return build_drive_item_path(item.get("parentReference") or {}, name) or None

    async def delete_file(self, item_id: str) -> None:
        await self._ensure_site_and_drive()
        client = await self.get_client()
        headers = await self.auth_headers()
        url = self.graph_url(f"{self._drive_resource}/items/{item_id}")
        resp = await client.delete(url, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph delete failed: {resp.status_code}")

    async def _get_item_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        await self._ensure_site_and_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Accept": "application/json;odata.metadata=none"})
        url = self.graph_url(f"{self._drive_resource}/root:/{path.strip('/')}")
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def _create_folder(self, parent_path: str, name: str) -> Dict[str, Any]:
        await self._ensure_site_and_drive()
        client = await self.get_client()
        headers = await self.auth_headers(extra={"Content-Type": "application/json", "Accept": "application/json;odata.metadata=none"})
        payload = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"}
        if parent_path:
            url = self.graph_url(f"{self._drive_resource}/root:/{parent_path.strip('/')}:/children")
        else:
            url = self.graph_url(f"{self._drive_resource}/root/children")
        resp = await client.post(url, headers=headers, json=payload)
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

    async def resolve_item_id(self, identifier: str) -> str:
        if "/" in identifier or ":" in identifier:
            item = await self._get_item_by_path(identifier)
            if not item:
                raise RuntimeError(f"Item not found for path: {identifier}")
            return item["id"]
        return identifier

    async def move_file(
        self,
        identifier: str,
        dest_folder_path: str,
        new_name: Optional[str] = None,
        conflict_behavior: str = "rename",
    ) -> Dict[str, Any]:
        await self._ensure_site_and_drive()
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
        url = self.graph_url(f"{self._drive_resource}/items/{item_id}")
        resp = await client.patch(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def test_connection(self) -> bool:
        try:
            await self._ensure_site_and_drive()
            await self.list_files("")
            return True
        except Exception as exc:
            dsx_logging.warning(f"SharePoint repo check failed: {exc}")
            return False

    # ---------------------- REST (SharePoint Online) helpers ----------------------
    def _spo_url(self, site_path: str, suffix: str) -> str:
        return f"https://{self._cfg.sp_hostname}/sites/{site_path.strip('/')}/{suffix.lstrip('/')}"

    async def _get_request_digest(self, site_path: str) -> str:
        import time

        ttl = int(getattr(self._cfg, "sp_digest_ttl_s", 1500) or 1500)
        key = site_path.strip("/") or "root"
        now = time.time()
        cached = self._digest_cache.get(key)
        if cached and now < cached[1]:
            return cached[0]
        client = await self.get_client()
        headers = await self._headers_spo()
        url = self._spo_url(site_path, "_api/contextinfo")
        resp = await client.post(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        digest = data.get("FormDigestValue")
        self._digest_cache[key] = (digest, now + ttl)
        return digest

    async def iter_list_items_rest(
        self,
        list_guid: str,
        view_xml: Optional[str] = None,
        row_limit: int = 5000,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield items from a SharePoint list using RenderListDataAsStream (fast, shaped rows)."""
        site_path = self._cfg.sp_site_path
        client = await self.get_client()
        headers = await self._headers_spo()
        digest = await self._get_request_digest(site_path)
        url = self._spo_url(site_path, f"_api/web/Lists(guid'{list_guid}')/RenderListDataAsStream")
        if not view_xml:
            view_xml = (
                "<View><Query><OrderBy><FieldRef Name='ID' Ascending='TRUE'/></OrderBy></Query>"
                f"<RowLimit>{row_limit}</RowLimit></View>"
            )
        payload = {
            "parameters": {
                "__metadata": {"type": "SP.RenderListDataParameters"},
                "RenderOptions": 2,
                "ViewXml": view_xml,
            }
        }
        next_pos: Optional[str] = None
        while True:
            body = payload.copy()
            if next_pos:
                body["parameters"]["Paging"] = {"ListItemCollectionPositionNext": next_pos}
            resp = await client.post(
                url,
                headers={
                    **headers,
                    "Content-Type": "application/json;odata=verbose",
                    "X-RequestDigest": digest,
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("Row") or data.get("ListData", {}).get("Row") or []
            for r in rows:
                yield r
            next_pos = data.get("ListData", {}).get("PositionInfo") or data.get("NextHref") or None
            if not next_pos:
                break

    @staticmethod
    def drive_path_from_filereF(file_ref: str, site_path: str) -> str:
        """Convert a SharePoint FileRef to a drive-relative path (strip '/sites/<site>/<library>/')."""
        path = file_ref or ""
        path = path.replace("\\", "/")
        parts = [seg for seg in path.split("/") if seg]
        try:
            idx = next(i for i, seg in enumerate(parts) if seg.lower() in {"sites", "teams"})
        except StopIteration:
            return "/".join(parts)
        rel_parts = parts[idx + 3 :]
        return "/".join(rel_parts)

    @staticmethod
    def parse_sharepoint_web_url(web_url: str) -> tuple[str, str, Optional[str], str]:
        """Parse a SharePoint web URL into (host, site_path, drive_name, drive_path)."""
        parsed = urlparse(web_url)
        host = parsed.netloc
        query = parse_qs(parsed.query)
        id_path = query.get("id", [None])[0]
        path = unquote(id_path or parsed.path)
        parts = [seg for seg in path.split("/") if seg]

        site_idx = -1
        for i, seg in enumerate(parts):
            if seg.lower() in {"sites", "teams"} and i + 1 < len(parts):
                site_idx = i
                break
        if site_idx == -1:
            raise ValueError("Unrecognized SharePoint URL – missing /sites/{name} or /teams/{name}")

        site_path = parts[site_idx + 1]
        drive_name = parts[site_idx + 2] if site_idx + 2 < len(parts) else None
        if drive_name and drive_name.lower().replace("%20", " ").replace("+", " ") in {"shared documents", "documents"}:
            drive_name = "Documents"
        sub_parts = parts[site_idx + 3 :] if drive_name else []
        drive_path = "/".join(sub_parts)
        return host, site_path, drive_name, drive_path

    @staticmethod
    def item_id_from_resource(resource: str) -> Optional[str]:
        if not resource:
            return None
        parts = resource.strip('/').split('/')
        for idx, seg in enumerate(parts):
            if seg.lower() == "items" and idx + 1 < len(parts):
                return parts[idx + 1]
        return None

    async def aclose(self):
        await super().close()
