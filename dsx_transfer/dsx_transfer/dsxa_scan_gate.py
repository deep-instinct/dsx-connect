from __future__ import annotations

from typing import Any, AsyncIterator, Protocol

from dsx_transfer.contracts import ScanGate
from dsx_transfer.models import ScanDecision, ScanObservation, TransferItem, TransferVerdict
from dsx_transfer.policy import GuardedTransferPolicy


class DsxaStreamClient(Protocol):
    async def scan_binary_stream(
        self,
        data: AsyncIterator[bytes],
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError


class DsxaStreamScanGate(ScanGate):
    def __init__(
        self,
        client: DsxaStreamClient,
        *,
        policy: GuardedTransferPolicy | None = None,
        policy_id: str | None = None,
        protected_entity: int | None = None,
        custom_metadata: str | None = None,
        password: str | None = None,
    ) -> None:
        self.client = client
        self.policy = policy or GuardedTransferPolicy(policy_id=policy_id)
        self.protected_entity = protected_entity
        self.custom_metadata = custom_metadata
        self.password = password

    async def decide(self, item: TransferItem, chunks: AsyncIterator[bytes]) -> ScanDecision:
        response = await self.client.scan_binary_stream(
            chunks,
            protected_entity=self.protected_entity,
            custom_metadata=self.custom_metadata,
            password=self.password,
        )
        observation = scan_observation_from_dsxa_response(response)
        return self.policy.evaluate(item=item, observation=observation)


def scan_observation_from_dsxa_response(response: Any) -> ScanObservation:
    verdict = _normalize_dsxa_verdict(_get_attr_or_key(response, "verdict"))
    file_info = _get_attr_or_key(response, "file_info")
    file_type = _get_attr_or_key(file_info, "file_type") if file_info is not None else None
    scan_guid = _get_attr_or_key(response, "scan_guid")
    details = _response_details(response)
    return ScanObservation(
        verdict=verdict,
        file_type=str(file_type) if file_type is not None else None,
        scan_guid=str(scan_guid) if scan_guid is not None else None,
        details=details,
    )


def _normalize_dsxa_verdict(value: Any) -> TransferVerdict:
    raw = getattr(value, "value", value)
    normalized = str(raw or "").strip().lower().replace("_", " ").replace("-", " ")
    if normalized == "benign":
        return "benign"
    if normalized == "malicious":
        return "malicious"
    if normalized in {"non compliant", "suspicious"}:
        return "suspicious"
    if normalized in {"unknown", "unsupported file type", "not scanned", "scanning"}:
        return "unknown"
    return "error"


def _get_attr_or_key(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _response_details(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json", exclude_none=True)
    if isinstance(response, dict):
        return dict(response)
    return {}
