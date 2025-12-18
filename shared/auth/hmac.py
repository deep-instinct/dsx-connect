from __future__ import annotations
import base64
import hashlib
import hmac as _hmac
import os
import time
from typing import Callable


def b64(v: bytes) -> str:
    return base64.b64encode(v).decode()


def build_message(method: str, path_q: str, ts: int | str, nonce: str, body: bytes | None) -> bytes:
    return f"{method.upper()}|{path_q}|{ts}|{nonce}|".encode() + (body or b"")


def make_hmac_header(key_id: str, secret: str, method: str, path_q: str, body: bytes | None,
                     ts: int | None = None, nonce: str | None = None) -> str:
    ts = int(ts or time.time())
    nonce = nonce or b64(os.urandom(12))
    msg = build_message(method, path_q, ts, nonce, body)
    sig = b64(_hmac.new(secret.encode(), msg, hashlib.sha256).digest())
    return f"DSX-HMAC key_id={key_id}, ts={ts}, nonce={nonce}, sig={sig}"


def parse_hmac_header(header: str) -> dict:
    if not header or not header.startswith("DSX-HMAC "):
        raise ValueError("missing_hmac")
    try:
        parts = dict(kv.strip().split("=", 1) for kv in header[len("DSX-HMAC "):].split(","))
        parts["ts"] = int(parts["ts"])  # normalize
        return parts
    except Exception as e:
        raise ValueError(f"malformed_hmac: {e}")


def verify_hmac(method: str, path_q: str, body: bytes | None, header: str,
                secret_lookup: Callable[[str], str | None], skew_seconds: int = 60) -> str:
    parts = parse_hmac_header(header)
    kid = parts.get("key_id")
    if not kid:
        raise ValueError("missing_key_id")
    secret = (secret_lookup(kid) or "")
    if not secret:
        raise ValueError("unknown_key_id")
    now = int(time.time())
    ts = int(parts.get("ts", 0))
    if abs(now - ts) > int(skew_seconds):
        raise ValueError("stale_request")
    exp = b64(_hmac.new(secret.encode(), build_message(method, path_q, ts, parts.get("nonce", ""), body), hashlib.sha256).digest())
    if not _hmac.compare_digest(exp, parts.get("sig", "")):
        raise ValueError("bad_signature")
    return kid

