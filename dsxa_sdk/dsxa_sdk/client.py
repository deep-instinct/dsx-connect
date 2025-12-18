from __future__ import annotations

import asyncio
import base64
import time
from enum import Enum
from pathlib import Path
import warnings
from typing import Any, Dict, Optional, Union

import httpx

from .exceptions import DSXAError, map_http_status
from .models import (
    ScanByPathResponse,
    ScanByPathVerdictResponse,
    ScanResponse,
)


class ScanMode(str, Enum):
    BINARY = "binary"
    BASE64 = "base64"


class _BaseDSXAClient:
    def __init__(
        self,
        base_url: str,
        auth_token: Optional[str] = None,
        *,
        default_protected_entity: Optional[int] = 1,
        default_metadata: Optional[str] = None,
        **_legacy_kwargs: Any,
    ):
        self.base_url = base_url.rstrip("/")
        legacy_api_token = _legacy_kwargs.pop("api_token", None)
        if legacy_api_token is not None:
            warnings.warn(
                "api_token is deprecated; pass auth_token instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        if _legacy_kwargs:
            unexpected = ", ".join(sorted(_legacy_kwargs.keys()))
            raise TypeError(f"Unexpected keyword argument(s): {unexpected}")
        token_source = auth_token if auth_token is not None else legacy_api_token
        token = token_source.strip() if isinstance(token_source, str) else token_source
        self._auth_token = token or None
        self._default_protected_entity = default_protected_entity
        self._default_metadata = default_metadata

    # -------- Context manager helpers --------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        raise NotImplementedError

    def _build_headers(
        self,
        *,
        protected_entity: Optional[int],
        custom_metadata: Optional[str],
        password: Optional[str],
        base64_flag: bool = False,
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/octet-stream",
        }
        entity = protected_entity if protected_entity is not None else self._default_protected_entity
        if entity is not None:
            headers["protected_entity"] = str(entity)
        metadata = custom_metadata if custom_metadata is not None else self._default_metadata
        if metadata:
            headers["X-Custom-Metadata"] = metadata
        if password:
            encoded = base64.b64encode(password.encode("utf-8")).decode("ascii")
            headers["scan_password"] = encoded
        if base64_flag:
            headers["X-Content-Type"] = "base64"
        return headers


class DSXAClient(_BaseDSXAClient):
    """
    Client SDK for DSX Application Scanner REST APIs (scan/binary, scan/base64, scan/by_hash, scan/by_path).

    The client maintains an httpx.Client underneath; close it via `close()` or use `with DSXAClient(...) as client: ...`.
    """

    def __init__(
        self,
        base_url: str,
        auth_token: Optional[str] = None,
        *,
        timeout: Optional[float] = 30.0,
        verify_tls: Union[bool, str] = True,
        http_proxy: Optional[str] = None,
        default_protected_entity: Optional[int] = 1,
        default_metadata: Optional[str] = None,
        **_legacy_kwargs: Any,
    ):
        super().__init__(
            base_url=base_url,
            auth_token=auth_token,
            default_protected_entity=default_protected_entity,
            default_metadata=default_metadata,
            **_legacy_kwargs,
        )
        client_kwargs: Dict[str, Any] = {
            "timeout": timeout,
            "verify": verify_tls,
        }
        if http_proxy:
            client_kwargs["proxies"] = http_proxy
        self._client = httpx.Client(**client_kwargs)

    def close(self) -> None:
        self._client.close()

    # -------- Public API --------
    def scan_binary(
        self,
        data: Union[bytes, memoryview],
        *,
        protected_entity: Optional[int] = None,
        custom_metadata: Optional[str] = None,
        password: Optional[str] = None,
        base64_header: bool = False,
    ) -> ScanResponse:
        """
        Scan a file in binary mode (optionally flagged as base64 via header).
        """
        headers = self._build_headers(
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
            password=password,
            base64_flag=base64_header,
        )
        response = self._request(
            "POST",
            "/scan/binary/v2",
            headers=headers,
            content=bytes(data),
        )
        return ScanResponse.model_validate(response)

    def scan_base64(
        self,
        encoded_data: Union[str, bytes],
        *,
        protected_entity: Optional[int] = None,
        custom_metadata: Optional[str] = None,
        password: Optional[str] = None,
    ) -> ScanResponse:
        """Scan a base64 encoded payload using the /scan/base64/v2 endpoint."""
        if isinstance(encoded_data, str):
            payload = encoded_data.encode("utf-8")
        else:
            payload = encoded_data
        headers = self._build_headers(
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
            password=password,
        )
        response = self._request(
            "POST",
            "/scan/base64/v2",
            headers=headers,
            content=payload,
        )
        return ScanResponse.model_validate(response)

    def scan_file(
        self,
        path: str,
        *,
        mode: ScanMode = ScanMode.BINARY,
        **kwargs: Any,
    ) -> ScanResponse:
        """Convenience helper to read a file from disk and scan it."""
        with open(path, "rb") as fh:
            data = fh.read()

        if mode == ScanMode.BASE64:
            encoded = base64.b64encode(data)
            return self.scan_base64(encoded, **kwargs)
        return self.scan_binary(data, **kwargs)

    def scan_hash(
        self,
        file_hash: str,
        *,
        protected_entity: Optional[int] = None,
        custom_metadata: Optional[str] = None,
    ) -> ScanResponse:
        """Submit a SHA256 hash for reputation-based scanning."""
        headers = self._build_headers(
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
        )
        response = self._request(
            "POST",
            "/scan/by_hash",
            headers=headers,
            content=file_hash.encode("utf-8"),
        )
        return ScanResponse.model_validate(response)

    def scan_by_path(
        self,
        stream_path: str,
        *,
        protected_entity: Optional[int] = None,
        custom_metadata: Optional[str] = None,
        password: Optional[str] = None,
    ) -> ScanByPathResponse:
        """
        Initiate a scan-by-path workflow for large files stored on remote filesystems.

        Returns a response with verdict="Scanning" and scan_guid which can be polled via `poll_scan_by_path`.
        """
        headers = self._build_headers(
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
            password=password,
        )
        headers["Stream-Path"] = stream_path
        response = self._request(
            "GET",
            "/scan/by_path",
            headers=headers,
        )
        return ScanByPathResponse.model_validate(response)

    def poll_scan_by_path(
        self,
        scan_guid: str,
        *,
        interval_seconds: float = 5.0,
        timeout_seconds: float = 900.0,
    ) -> ScanByPathVerdictResponse:
        """
        Poll `/result/by_path` until a terminal verdict is returned or timeout elapses.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            response = self.get_scan_by_path_result(scan_guid)
            if response.verdict not in {"Scanning"}:
                return response
            if time.monotonic() >= deadline:
                return response
            time.sleep(interval_seconds)

    def get_scan_by_path_result(
        self,
        scan_guid: str,
    ) -> ScanByPathVerdictResponse:
        """Retrieve the latest verdict for a scan initiated via scan_by_path."""
        payload = {"scan_guid": scan_guid}
        response = self._request(
            "POST",
            "/result/by_path",
            json=payload,
        )
        return ScanByPathVerdictResponse.model_validate(response)

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        content: Optional[bytes] = None,
        json: Optional[Any] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        merged_headers: Dict[str, str] = {}
        if self._auth_token:
            merged_headers["Authorization"] = f"Bearer {self._auth_token}"
        if headers:
            merged_headers.update(headers)
        try:
            response = self._client.request(
                method,
                url,
                headers=merged_headers,
                content=content,
                json=json,
            )
        except httpx.HTTPError as exc:
            raise DSXAError(str(exc)) from exc

        if response.status_code >= 400:
            raise map_http_status(response.status_code, response.text or response.reason_phrase)
        if not response.content:
            return {}
        return response.json()


class AsyncDSXAClient(_BaseDSXAClient):
    """
    Async variant of the DSXA client using httpx.AsyncClient. Suitable for batching uploads via asyncio.
    """

    def __init__(
        self,
        base_url: str,
        auth_token: Optional[str] = None,
        *,
        timeout: Optional[float] = 30.0,
        verify_tls: Union[bool, str] = True,
        http_proxy: Optional[str] = None,
        default_protected_entity: Optional[int] = 1,
        default_metadata: Optional[str] = None,
        **_legacy_kwargs: Any,
    ):
        super().__init__(
            base_url=base_url,
            auth_token=auth_token,
            default_protected_entity=default_protected_entity,
            default_metadata=default_metadata,
            **_legacy_kwargs,
        )
        client_kwargs: Dict[str, Any] = {
            "timeout": timeout,
            "verify": verify_tls,
        }
        if http_proxy:
            client_kwargs["proxies"] = http_proxy
        self._client = httpx.AsyncClient(**client_kwargs)

    async def __aenter__(self) -> "AsyncDSXAClient":
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    def close(self) -> None:
        self._client.close()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def scan_binary(
        self,
        data: Union[bytes, memoryview],
        *,
        protected_entity: Optional[int] = None,
        custom_metadata: Optional[str] = None,
        password: Optional[str] = None,
        base64_header: bool = False,
    ) -> ScanResponse:
        headers = self._build_headers(
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
            password=password,
            base64_flag=base64_header,
        )
        response = await self._request(
            "POST",
            "/scan/binary/v2",
            headers=headers,
            content=bytes(data),
        )
        return ScanResponse.model_validate(response)

    async def scan_base64(
        self,
        encoded_data: Union[str, bytes],
        *,
        protected_entity: Optional[int] = None,
        custom_metadata: Optional[str] = None,
        password: Optional[str] = None,
    ) -> ScanResponse:
        if isinstance(encoded_data, str):
            payload = encoded_data.encode("utf-8")
        else:
            payload = encoded_data
        headers = self._build_headers(
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
            password=password,
        )
        response = await self._request(
            "POST",
            "/scan/base64/v2",
            headers=headers,
            content=payload,
        )
        return ScanResponse.model_validate(response)

    async def scan_file(
        self,
        path: str,
        *,
        mode: ScanMode = ScanMode.BINARY,
        **kwargs: Any,
    ) -> ScanResponse:
        data = await asyncio.to_thread(lambda: Path(path).read_bytes())
        if mode == ScanMode.BASE64:
            encoded = base64.b64encode(data)
            return await self.scan_base64(encoded, **kwargs)
        return await self.scan_binary(data, **kwargs)

    async def scan_hash(
        self,
        file_hash: str,
        *,
        protected_entity: Optional[int] = None,
        custom_metadata: Optional[str] = None,
    ) -> ScanResponse:
        headers = self._build_headers(
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
        )
        response = await self._request(
            "POST",
            "/scan/by_hash",
            headers=headers,
            content=file_hash.encode("utf-8"),
        )
        return ScanResponse.model_validate(response)

    async def scan_by_path(
        self,
        stream_path: str,
        *,
        custom_metadata: Optional[str] = None,
        password: Optional[str] = None,
        protected_entity: Optional[int] = None,
    ) -> ScanByPathResponse:
        headers = self._build_headers(
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
            password=password,
        )
        headers["Stream-Path"] = stream_path
        response = await self._request(
            "GET",
            "/scan/by_path",
            headers=headers,
        )
        return ScanByPathResponse.model_validate(response)

    async def poll_scan_by_path(
        self,
        scan_guid: str,
        *,
        interval_seconds: float = 5.0,
        timeout_seconds: float = 900.0,
    ) -> ScanByPathVerdictResponse:
        deadline = time.monotonic() + timeout_seconds
        while True:
            response = await self.get_scan_by_path_result(scan_guid)
            if response.verdict not in {"Scanning"}:
                return response
            if time.monotonic() >= deadline:
                return response
            await asyncio.sleep(interval_seconds)

    async def get_scan_by_path_result(
        self,
        scan_guid: str,
    ) -> ScanByPathVerdictResponse:
        payload = {"scan_guid": scan_guid}
        response = await self._request(
            "POST",
            "/result/by_path",
            json=payload,
        )
        return ScanByPathVerdictResponse.model_validate(response)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        content: Optional[bytes] = None,
        json: Optional[Any] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        merged_headers: Dict[str, str] = {}
        if self._auth_token:
            merged_headers["Authorization"] = f"Bearer {self._auth_token}"
        if headers:
            merged_headers.update(headers)
        try:
            response = await self._client.request(
                method,
                url,
                headers=merged_headers,
                content=content,
                json=json,
            )
        except httpx.HTTPError as exc:
            raise DSXAError(str(exc)) from exc

        if response.status_code >= 400:
            raise map_http_status(response.status_code, response.text or response.reason_phrase)
        if not response.content:
            return {}
        return response.json()
