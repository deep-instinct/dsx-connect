"""
Integration tests against a live DSXA scanner.

Set DSXA_BASE_URL and DSXA_AUTH_TOKEN to enable.
"""

from __future__ import annotations

import os

import pytest

from dsxa_sdk import DSXAClient, VerdictEnum

BASE_URL = os.getenv("DSXA_BASE_URL")
AUTH_TOKEN = os.getenv("DSXA_AUTH_TOKEN")
PROTECTED_ENTITY = os.getenv("DSXA_PROTECTED_ENTITY")
VERIFY_TLS = (os.getenv("DSXA_VERIFY_TLS", "true").lower() == "true")

pytestmark = pytest.mark.dsxa_integration


@pytest.fixture(scope="module")
def dsxa_client():
    if not BASE_URL or not AUTH_TOKEN:
        pytest.skip("Set DSXA_BASE_URL and DSXA_AUTH_TOKEN to run integration tests.")
    pe = int(PROTECTED_ENTITY) if PROTECTED_ENTITY else None
    client = DSXAClient(
        base_url=BASE_URL,
        auth_token=AUTH_TOKEN,
        default_protected_entity=pe,
        verify_tls=VERIFY_TLS,
    )
    yield client
    client.close()


def test_live_binary_scan(dsxa_client):
    eicar = (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )
    resp = dsxa_client.scan_binary(
        eicar,
        custom_metadata="sdk-integration-test",
    )
    assert resp.scan_guid
    assert resp.verdict in {
        VerdictEnum.MALICIOUS,
        VerdictEnum.NOT_SCANNED,
        VerdictEnum.NON_COMPLIANT,
        VerdictEnum.BENIGN,
    }
