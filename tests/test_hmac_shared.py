import time
from shared.auth.hmac import make_hmac_header, verify_hmac


def test_hmac_roundtrip_basic():
    key_id = "kid"
    secret = "s3cr3t"
    method = "POST"
    path_q = "/x/y?z=1"
    body = b"{\"a\":1}"

    # Use current timestamp so the request is not considered stale
    hdr = make_hmac_header(key_id, secret, method, path_q, body)

    def lookup(k):
        return secret if k == key_id else None

    kid = verify_hmac(method, path_q, body, hdr, lookup, skew_seconds=300)
    assert kid == key_id
