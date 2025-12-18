"""Subscription manager for Microsoft Graph change notifications.

Reconciles subscriptions on /users/{id}/messages and renews them periodically.
Stateless: relies on Microsoft Graph as system of record. No connector Redis storage.
"""

import httpx
from typing import Iterable


class SubscriptionManager:
    def __init__(self, token_getter):
        """token_getter: async callable -> str (Bearer token)"""
        self._token_getter = token_getter

    async def list_all(self) -> list[dict]:
        token = await self._token_getter()
        url = "https://graph.microsoft.com/v1.0/subscriptions"
        subs: list[dict] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            next_url = url
            while next_url:
                r = await client.get(next_url, headers={"Authorization": f"Bearer {token}"})
                r.raise_for_status()
                data = r.json()
                subs.extend(data.get("value", []))
                next_url = data.get("@odata.nextLink")
        return subs

    async def create_for_user(self, user_upn: str, notification_url: str, change_type: str = "created,updated",
                               expiry_hours: int = 48, client_state: str | None = None) -> dict:
        token = await self._token_getter()
        import datetime as dt
        expiry = (dt.datetime.utcnow() + dt.timedelta(hours=expiry_hours)).replace(microsecond=0).isoformat() + "Z"
        payload = {
            "changeType": change_type,
            "notificationUrl": notification_url,
            "resource": f"users/{user_upn}/messages",
            "expirationDateTime": expiry,
        }
        if client_state:
            payload["clientState"] = client_state
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post("https://graph.microsoft.com/v1.0/subscriptions", json=payload,
                                  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            r.raise_for_status()
            return r.json()

    async def renew(self, sub_id: str, expiry_hours: int = 48) -> None:
        token = await self._token_getter()
        import datetime as dt
        expiry = (dt.datetime.utcnow() + dt.timedelta(hours=expiry_hours)).replace(microsecond=0).isoformat() + "Z"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.patch(f"https://graph.microsoft.com/v1.0/subscriptions/{sub_id}",
                                   json={"expirationDateTime": expiry},
                                   headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            r.raise_for_status()

    async def reconcile_for_upns(self, upns: Iterable[str], notification_url: str) -> dict:
        """Ensure we have active subs per UPN for /messages to our notification_url.
        Returns a summary dict.
        """
        existing = await self.list_all()
        by_key = {}
        for s in existing:
            res = s.get("resource", "")
            nurl = s.get("notificationUrl", "")
            # Key on (resource, notificationUrl)
            by_key[(res, nurl)] = s
        created = 0
        renewed = 0
        for u in upns:
            key = (f"users/{u}/messages", notification_url)
            if key in by_key:
                try:
                    await self.renew(by_key[key]["id"])
                    renewed += 1
                except Exception:
                    # Attempt create if renew fails
                    await self.create_for_user(u, notification_url)
                    created += 1
            else:
                await self.create_for_user(u, notification_url)
                created += 1
        return {"created": created, "renewed": renewed}
