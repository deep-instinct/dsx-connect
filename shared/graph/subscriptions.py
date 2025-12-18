from __future__ import annotations

import datetime as dt
from typing import Awaitable, Callable, Dict, List, Optional

import httpx


class GraphDriveSubscriptionManager:
    """Manage Microsoft Graph subscriptions for a specific drive resource."""

    GRAPH_SUBSCRIPTIONS_URL = "https://graph.microsoft.com/v1.0/subscriptions"

    def __init__(self, token_getter: Callable[[], Awaitable[str]], resource: str):
        self._token_getter = token_getter
        self._resource = resource

    async def _auth_headers(self) -> dict:
        token = await self._token_getter()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def list_all(self) -> List[dict]:
        headers = await self._auth_headers()
        subs: List[dict] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            next_url: Optional[str] = self.GRAPH_SUBSCRIPTIONS_URL
            while next_url:
                resp = await client.get(next_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                subs.extend(data.get("value", []))
                next_url = data.get("@odata.nextLink")
        return subs

    async def create(
        self,
        notification_url: str,
        *,
        change_types: str = "updated",
        client_state: Optional[str] = None,
        expiry_minutes: int = 60,
    ) -> dict:
        headers = await self._auth_headers()
        expires = (dt.datetime.utcnow().replace(microsecond=0) + dt.timedelta(minutes=expiry_minutes)).isoformat() + "Z"
        payload = {
            "resource": self._resource,
            "changeType": change_types,
            "notificationUrl": notification_url,
            "expirationDateTime": expires,
            "latestSupportedTlsVersion": "v1_2",
        }
        if client_state:
            payload["clientState"] = client_state
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.GRAPH_SUBSCRIPTIONS_URL, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def renew(self, subscription_id: str, *, expiry_minutes: int = 60) -> None:
        headers = await self._auth_headers()
        expires = (dt.datetime.utcnow().replace(microsecond=0) + dt.timedelta(minutes=expiry_minutes)).isoformat() + "Z"
        url = f"{self.GRAPH_SUBSCRIPTIONS_URL}/{subscription_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(url, json={"expirationDateTime": expires}, headers=headers)
            resp.raise_for_status()

    async def reconcile(
        self,
        notification_url: str,
        *,
        change_types: str = "updated",
        client_state: Optional[str] = None,
        expiry_minutes: int = 60,
    ) -> dict:
        """Ensure a subscription exists for this drive resource."""
        summary = {"created": 0, "renewed": 0, "resource": self._resource}
        subs = await self.list_all()
        matches = [
            s
            for s in subs
            if s.get("resource") == self._resource and s.get("notificationUrl") == notification_url
        ]
        if matches:
            sub = matches[0]
            if self._needs_renewal(sub, expiry_minutes):
                await self.renew(sub["id"], expiry_minutes=expiry_minutes)
                summary["renewed"] += 1
        else:
            await self.create(
                notification_url,
                change_types=change_types,
                client_state=client_state,
                expiry_minutes=expiry_minutes,
            )
            summary["created"] += 1
        return summary

    @staticmethod
    def _needs_renewal(subscription: dict, desired_minutes: int) -> bool:
        expiry_raw = subscription.get("expirationDateTime")
        if not expiry_raw:
            return True
        try:
            expiry_dt = dt.datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
        except Exception:
            return True
        remaining = expiry_dt - dt.datetime.now(dt.timezone.utc)
        threshold = dt.timedelta(minutes=max(15, desired_minutes // 2))
        return remaining < threshold
