# dsx_connect/connectors/client.py
from contextlib import contextmanager, asynccontextmanager
import json, threading, asyncio
from typing import Optional, Mapping, Any, Literal, Tuple, Union

# Allow tests to monkeypatch `httpx` and survive reloads
try:  # pragma: no cover - conditional import to support monkeypatch+reload in tests
    httpx  # type: ignore[name-defined]
except NameError:  # pragma: no cover
    import httpx

from dsx_connect.config import get_config
from shared.auth.hmac import make_hmac_header
from shared.routes import service_url

HttpMethod = Literal["GET","POST","PUT","PATCH","DELETE"]

# Pools
_sync_pool: dict[str, Any] = {}
_async_pool: dict[str, Any] = {}
_sync_lock = threading.Lock()
_async_lock = asyncio.Lock()

# Resolve environment once (it's a small helper over get_config())
_CFG = get_config()

def _signed_headers(
        url: str,
        method: str,
        body: bytes,
        key_id: Optional[str],
        secret: Optional[str],
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not key_id or not secret:
        return headers

    # Path + optional query for signature
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    path_q = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    headers["Authorization"] = make_hmac_header(key_id, secret, method, path_q, body)
    return headers


def _conn_parts(conn: Union[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    if isinstance(conn, str):
        # No global fallback; HMAC creds are provisioned per-connector
        return conn, None, None
    # Prefer explicit per-connector creds when present; else fallback to global outbound
    url = getattr(conn, "url", conn)
    key_id = getattr(conn, "hmac_key_id", None)
    secret = getattr(conn, "hmac_secret", None)
    # Fallback: if missing, try to look up from Redis by connector UUID (server-side provisioning)
    if (not key_id or not secret) and hasattr(conn, "uuid") and getattr(conn, "uuid", None):
        try:
            import redis  # sync client
            from dsx_connect.messaging.connector_keys import ConnectorKeys
            r = redis.Redis.from_url(str(get_config().redis_url), decode_responses=True)
            hm = r.hgetall(ConnectorKeys.config(str(getattr(conn, "uuid"))))
            if isinstance(hm, dict):
                key_id = key_id or hm.get("hmac_key_id")
                secret = secret or hm.get("hmac_secret")
        except Exception:
            pass
    # Keys are expected to be provisioned per-connector at registration
    return (url, key_id, secret)


@asynccontextmanager
async def get_async_connector_client(conn):
    async with _async_lock:
        url, key_id, secret = _conn_parts(conn)
        http = _async_pool.setdefault(url, httpx.AsyncClient(verify=False, timeout=30.0))

    class AClient:
        async def request(self, method: HttpMethod, path: str,
                          json_body: Optional[Mapping[str, Any]] = None,
                          headers: Optional[dict[str, str]] = None,
                          params: Optional[Mapping[str, Any]] = None) -> Any:
            base_url = service_url(url, path)
            # Build query string if provided for signing and request
            if params:
                from urllib.parse import urlencode
                qs = urlencode(params, doseq=True)
                full_url = f"{base_url}?{qs}"
            else:
                full_url = base_url
            body = b"" if json_body is None else json.dumps(json_body, separators=(",", ":")).encode()
            hdrs = _signed_headers(full_url, method, body, key_id, secret)
            if headers:
                hdrs.update(headers)
            # Since full_url already contains params (if any), do not also pass params to httpx
            return await http.request(method, full_url, content=(body or None), headers=hdrs)

        async def get(self, path, headers=None, params: Optional[Mapping[str, Any]] = None):
            return await self.request("GET", path, None, headers, params)

        async def post(self, path, json_body=None, headers=None, params: Optional[Mapping[str, Any]] = None):
            return await self.request("POST", path, json_body, headers, params)

        async def put(self, path, json_body=None, headers=None, params: Optional[Mapping[str, Any]] = None):
            return await self.request("PUT", path, json_body, headers, params)

        async def delete(self, path, headers=None, params: Optional[Mapping[str, Any]] = None):
            return await self.request("DELETE", path, None, headers, params)

        async def get_json(self, path):
            """Get JSON response. Raises httpx exceptions transparently."""
            response = await self.request("GET", path)
            response.raise_for_status()
            return response.json()

        async def post_json(self, path, json_body=None):
            """Post JSON and get JSON response. Raises httpx exceptions transparently."""
            response = await self.request("POST", path, json_body)
            response.raise_for_status()
            return response.json()

    try:
        yield AClient()
    finally:
        pass


@contextmanager
def get_connector_client(conn):
    with _sync_lock:
        url, key_id, secret = _conn_parts(conn)
        http = _sync_pool.setdefault(url, httpx.Client(verify=False, timeout=30.0))

    class SClient:
        def request(self, method: HttpMethod, path: str,
                    json_body: Optional[Mapping[str, Any]] = None,
                    headers: Optional[dict[str, str]] = None,
                    params: Optional[Mapping[str, Any]] = None) -> Any:
            base_url = service_url(url, path)
            if params:
                from urllib.parse import urlencode
                qs = urlencode(params, doseq=True)
                full_url = f"{base_url}?{qs}"
            else:
                full_url = base_url
            body = b"" if json_body is None else json.dumps(json_body, separators=(",", ":")).encode()
            hdrs = _signed_headers(full_url, method, body, key_id, secret)
            if headers:
                hdrs.update(headers)
            return http.request(method, full_url, content=(body or None), headers=hdrs)

        def get(self, path, headers=None, params: Optional[Mapping[str, Any]] = None):
            return self.request("GET", path, None, headers, params)
        def post(self, path, json_body=None, headers=None, params: Optional[Mapping[str, Any]] = None):
            return self.request("POST", path, json_body, headers, params)
        def put(self, path, json_body=None, headers=None, params: Optional[Mapping[str, Any]] = None):
            return self.request("PUT", path, json_body, headers, params)
        def delete(self, path, headers=None, params: Optional[Mapping[str, Any]] = None):
            return self.request("DELETE", path, None, headers, params)

        def get_json(self, path):            r = self.get(path); r.raise_for_status(); return r.json()
        def post_json(self, path, json_body=None): r = self.post(path, json_body); r.raise_for_status(); return r.json()

    try:
        yield SClient()
    finally:
        pass
