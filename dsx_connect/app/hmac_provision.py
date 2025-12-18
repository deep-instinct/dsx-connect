import base64, os
from typing import Optional, Tuple
from redis.asyncio import Redis
from dsx_connect.messaging.connector_keys import ConnectorKeys


def _b64(n: int = 32) -> str:
    return base64.b64encode(os.urandom(n)).decode()


async def ensure_hmac_for_connector(r: Optional[Redis], connector_uuid: str) -> Tuple[Optional[str], Optional[str]]:
    """Ensure per-connector HMAC creds exist in Redis; return (key_id, secret).

    Stores under ConnectorKeys.config(uuid) with fields hmac_key_id/hmac_secret.
    """
    if r is None or not connector_uuid:
        return None, None
    key = ConnectorKeys.config(connector_uuid)
    try:
        vals = await r.hmget(key, "hmac_key_id", "hmac_secret")
        kid, sec = (vals[0], vals[1]) if vals else (None, None)
        kid = kid.decode() if isinstance(kid, (bytes, bytearray)) else kid
        sec = sec.decode() if isinstance(sec, (bytes, bytearray)) else sec
        if kid and sec:
            return kid, sec
        # generate
        kid = _b64(12)
        sec = _b64(32)
        await r.hset(key, mapping={"hmac_key_id": kid, "hmac_secret": sec})
        try:
            # Write key-id index for inbound lookups
            await r.set(f"dsxconnect:hmac:kid:{kid}", connector_uuid)
        except Exception:
            pass
        # keep alongside presence; do not set a TTL (or consider aligning)
        return kid, sec
    except Exception:
        return None, None


async def get_hmac_for_connector(r: Optional[Redis], connector_uuid: str) -> Tuple[Optional[str], Optional[str]]:
    if r is None or not connector_uuid:
        return None, None
    try:
        key = ConnectorKeys.config(connector_uuid)
        vals = await r.hmget(key, "hmac_key_id", "hmac_secret")
        kid, sec = (vals[0], vals[1]) if vals else (None, None)
        kid = kid.decode() if isinstance(kid, (bytes, bytearray)) else kid
        sec = sec.decode() if isinstance(sec, (bytes, bytearray)) else sec
        return kid, sec
    except Exception:
        return None, None
