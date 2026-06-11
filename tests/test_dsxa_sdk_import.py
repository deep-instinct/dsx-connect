import sys
import types

from dsx_connect.dsxa_sdk_import import ensure_sdk_on_path


def test_ensure_sdk_on_path_replaces_cached_namespace_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "dsxa_sdk_py", types.ModuleType("dsxa_sdk_py"))

    ensure_sdk_on_path()

    from dsxa_sdk_py import DSXAClient

    assert DSXAClient.__name__ == "DSXAClient"
