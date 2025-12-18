"""Microsoft Graph client helpers for m365-mail-connector.

Implements client-credentials auth and helpers to list and download attachments.
"""

import msal  # type: ignore
import httpx
from typing import AsyncIterator, Any


class GraphClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, authority: str = "https://login.microsoftonline.com"):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.authority = authority.rstrip("/")
        self._cca = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            authority=f"{self.authority}/{self.tenant_id}",
            client_credential=self.client_secret,
        )

    async def token(self) -> str:
        # msal client is sync; call in thread if needed. For simplicity use acquire_token_silent first, then for_client.
        result = self._cca.acquire_token_silent(["https://graph.microsoft.com/.default"], account=None)
        if not result:
            result = self._cca.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in result:
            raise RuntimeError(f"Failed to acquire Graph token: {result}")
        return result["access_token"]

    async def fetch_message_min(self, user: str, message_id: str) -> dict:
        token = await self.token()
        url = f"https://graph.microsoft.com/v1.0/users/{user}/messages/{message_id}?$select=id,subject,hasAttachments,createdDateTime,internetMessageId"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return r.json()

    async def list_attachments(self, user: str, message_id: str) -> list[dict[str, Any]]:
        token = await self.token()
        url = f"https://graph.microsoft.com/v1.0/users/{user}/messages/{message_id}/attachments?$select=id,name,contentType,size,@odata.type"
        items: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            next_url = url
            while next_url:
                r = await client.get(next_url, headers={"Authorization": f"Bearer {token}"})
                r.raise_for_status()
                data = r.json()
                items.extend(data.get("value", []))
                next_url = data.get("@odata.nextLink")
        return items

    async def download_attachment(self, user: str, message_id: str, attachment_id: str) -> AsyncIterator[bytes]:
        token = await self.token()
        url = f"https://graph.microsoft.com/v1.0/users/{user}/messages/{message_id}/attachments/{attachment_id}/$value"
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk

    async def delta_messages(self, user: str, token_or_url: str | None = None) -> tuple[list[dict], str | None, str | None]:
        """
        Fetch changed messages via Graph delta. If token_or_url is a deltaLink or nextLink, follow it;
        else start from the default delta endpoint under Inbox.
        Returns (messages, next_link, delta_link) where:
          - next_link is @odata.nextLink (more pages in current delta session)
          - delta_link is @odata.deltaLink (bookmark for the next run)
        """
        token = await self.token()
        if token_or_url and token_or_url.startswith("https://"):
            url = token_or_url
        else:
            # Initial delta under Inbox; select minimal fields
            url = (
                f"https://graph.microsoft.com/v1.0/users/{user}/mailFolders('inbox')/messages/delta"
                f"?$select=id,hasAttachments,internetMessageId,createdDateTime"
            )
        items: list[dict] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
            items.extend(data.get("value", []))
            next_link = data.get("@odata.nextLink")
            delta_link = data.get("@odata.deltaLink")
        return items, next_link, delta_link

    async def fetch_message_body(self, user: str, message_id: str) -> dict:
        token = await self.token()
        url = f"https://graph.microsoft.com/v1.0/users/{user}/messages/{message_id}?$select=subject,body"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return r.json()

    async def patch_message_body_html(self, user: str, message_id: str, new_html: str) -> None:
        token = await self.token()
        url = f"https://graph.microsoft.com/v1.0/users/{user}/messages/{message_id}"
        payload = {"body": {"contentType": "html", "content": new_html}}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.patch(url, json=payload, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            r.raise_for_status()

    async def delete_attachment(self, user: str, message_id: str, attachment_id: str) -> None:
        token = await self.token()
        url = f"https://graph.microsoft.com/v1.0/users/{user}/messages/{message_id}/attachments/{attachment_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.delete(url, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()

    async def find_or_create_folder(self, user: str, display_name: str) -> str:
        token = await self.token()
        base = f"https://graph.microsoft.com/v1.0/users/{user}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Try find
            r = await client.get(f"{base}/mailFolders?$filter=displayName eq '{display_name}'&$select=id,displayName", headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
            for f in data.get("value", []):
                if f.get("displayName") == display_name:
                    return f.get("id")
            # Create
            r2 = await client.post(f"{base}/mailFolders", json={"displayName": display_name}, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            r2.raise_for_status()
            return r2.json().get("id")

    async def move_message(self, user: str, message_id: str, dest_folder_id: str) -> None:
        token = await self.token()
        url = f"https://graph.microsoft.com/v1.0/users/{user}/messages/{message_id}/move"
        payload = {"destinationId": dest_folder_id}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            r.raise_for_status()
