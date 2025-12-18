import importlib
import os

import pytest


def reload_auth():
    import dsx_connect.config as cfg
    importlib.reload(cfg)
    import dsx_connect.app.auth_jwt as auth
    importlib.reload(auth)
    return auth


def test_issue_and_verify_jwt_roundtrip(monkeypatch):
    monkeypatch.setenv("DSXCONNECT_AUTH__ENABLED", "true")
    monkeypatch.setenv("DSXCONNECT_AUTH__JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("DSXCONNECT_AUTH__JWT_TTL", "120")
    auth = reload_auth()

    payload = auth.issue_access_token(connector_uuid="abc-123")
    assert payload["token_type"] == "Bearer"
    assert payload["expires_in"] <= 120

    claims = auth.verify_access_token(payload["access_token"])
    assert claims.get("sub") == "abc-123"
    assert claims.get("role") == "connector"
    assert claims.get("aud") == "dsx-connect"
    assert claims.get("iss") == "dsx-connect"


def test_verify_enrollment_token(monkeypatch):
    monkeypatch.setenv("DSXCONNECT_AUTH__ENABLED", "true")
    monkeypatch.setenv("DSXCONNECT_AUTH__ENROLLMENT_TOKEN", "enroll-xyz")
    auth = reload_auth()
    assert auth.verify_enrollment_token("enroll-xyz") is True
    assert auth.verify_enrollment_token("nope") is False

