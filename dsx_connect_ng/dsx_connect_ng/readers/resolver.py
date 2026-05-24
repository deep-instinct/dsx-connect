from __future__ import annotations

from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.config_models import parse_integration_runtime_config
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.readers.base import Reader
from dsx_connect_ng.readers.cached import CachedArtifactReader
from dsx_connect_ng.readers.contracts import ReaderStrategy
from dsx_connect_ng.readers.local_path import LocalPathReader
from dsx_connect_ng.readers.proxy import build_connector_proxy_reader


def _reader_strategy_from_request(request: ScanItemRequested) -> ReaderStrategy | None:
    for source in (request.scan_options, request.read_hint):
        for key in ("readerStrategy", "reader_strategy"):
            value = source.get(key)
            if value in {"proxy", "native", "cached", "quarantine"}:
                return value
    return None


def _reader_strategy_from_integration(
    request: ScanItemRequested,
    *,
    control_plane: ControlPlaneService | None,
) -> ReaderStrategy | None:
    if control_plane is None or not request.integration_id:
        return None
    integration = control_plane.get_integration_or_404(request.integration_id)
    runtime_config = parse_integration_runtime_config(integration.config)
    return runtime_config.reader.default_strategy if runtime_config.reader and runtime_config.reader.default_strategy else runtime_config.reader_strategy


def resolve_reader_strategy(
    request: ScanItemRequested,
    *,
    control_plane: ControlPlaneService | None = None,
) -> ReaderStrategy:
    return (
        _reader_strategy_from_request(request)
        or _reader_strategy_from_integration(request, control_plane=control_plane)
        or settings.readers.default_strategy
    )


def build_scan_reader(
    request: ScanItemRequested,
    *,
    control_plane: ControlPlaneService | None = None,
) -> Reader:
    strategy = resolve_reader_strategy(request, control_plane=control_plane)
    if strategy == "proxy":
        return build_connector_proxy_reader(request, control_plane=control_plane)
    if strategy == "cached":
        return CachedArtifactReader()
    return LocalPathReader()
