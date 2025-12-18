# dsx_connect/dsxa_client/dsxa_client.py (Optimized)

import io
import logging
import asyncio
from typing import List, Optional
import httpx
from dsx_connect.dsxa_client.verdict_models import DPAVerdictModel2
from shared.models.status_responses import StatusResponse, StatusResponseEnum
from shared.dsx_logging import dsx_logging

CHUNK_SIZE = 1024 * 1024


class DSXAScanRequest:
    def __init__(self, binary_data: io.BytesIO, metadata_info: str = None, protected_entity: str = None):
        self.binary_data = binary_data
        self.metadata_info = metadata_info
        self.protected_entity = protected_entity


class DSXAClientError(Exception):
    """Base exception for DSXA client errors"""
    pass


class DSXAConnectionError(DSXAClientError):
    """Raised when unable to connect to DSXA service"""
    pass


class DSXAServiceError(DSXAClientError):
    """Raised when DSXA service returns an error"""
    pass


class DSXATimeoutError(DSXAClientError):
    """Raised when DSXA service times out"""
    pass


class DSXAClient:
    def __init__(self, scan_binary_url: str,
                 scan_concurrent_connections: int = 5,
                 timeout: int = 600,
                 enable_client_retry: bool = False):  # NEW: Allow disabling client retry
        self._scan_binary_url = scan_binary_url
        self._scan_concurrent_connections = scan_concurrent_connections
        self._enable_client_retry = enable_client_retry
        self._client_config = {
            "timeout": httpx.Timeout(timeout, read=timeout, connect=timeout),
            "limits": httpx.Limits(max_connections=scan_concurrent_connections),
            "verify": False
        }
        # Lazy initialization
        self._sync_client: Optional[httpx.Client] = None
        self._async_client: Optional[httpx.AsyncClient] = None

    @property
    def sync_client(self) -> httpx.Client:
        """Lazy sync client initialization."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(**self._client_config)
        return self._sync_client

    @property
    def async_client(self) -> httpx.AsyncClient:
        """Lazy async client initialization."""
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(**self._client_config)
        return self._async_client

    def close(self):
        """Close all clients."""
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None
        if self._async_client:
            # Note: This is sync close, for async use aclose()
            try:
                asyncio.get_event_loop().run_until_complete(self._async_client.aclose())
            except RuntimeError:
                # If no event loop, just set to None
                pass
            self._async_client = None

    async def aclose(self):
        """Async close for async clients."""
        if self._async_client:
            await self._async_client.aclose()
            self._async_client = None
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()

    def __str__(self):
        return f'DSXA Client: {self._scan_binary_url}'

    def _handle_connection_error(self, error: Exception, is_async: bool = False) -> Exception:
        """Convert low-level connection errors to more descriptive exceptions"""
        error_str = str(error)
        method_type = "async" if is_async else "sync"

        # Connection refused (service not running)
        if "Connection refused" in error_str or "[Errno 61]" in error_str:
            return DSXAConnectionError(
                f"Unable to connect to DSXA scanner at {self._scan_binary_url}. "
                f"Please verify the scanner service is running and accessible. "
                f"Original error: {error_str}"
            )

        # Name resolution failed (DNS/hostname issues)
        if "Name or service not known" in error_str or "[Errno -2]" in error_str or "getaddrinfo failed" in error_str:
            return DSXAConnectionError(
                f"Cannot resolve hostname for DSXA scanner at {self._scan_binary_url}. "
                f"Please check the URL and network connectivity. "
                f"Original error: {error_str}"
            )

        # Network unreachable
        if "Network is unreachable" in error_str or "[Errno 101]" in error_str:
            return DSXAConnectionError(
                f"Network unreachable to DSXA scanner at {self._scan_binary_url}. "
                f"Please check network connectivity and firewall settings. "
                f"Original error: {error_str}"
            )

        # Connection timeout
        if "timeout" in error_str.lower() or "timed out" in error_str.lower():
            return DSXATimeoutError(
                f"Connection to DSXA scanner at {self._scan_binary_url} timed out. "
                f"The service may be overloaded or slow to respond. "
                f"Original error: {error_str}"
            )

        # SSL/TLS errors
        if "ssl" in error_str.lower() or "certificate" in error_str.lower():
            return DSXAConnectionError(
                f"SSL/TLS error connecting to DSXA scanner at {self._scan_binary_url}. "
                f"Please check certificate configuration. "
                f"Original error: {error_str}"
            )

        # Generic connection error
        return DSXAConnectionError(
            f"Failed to connect to DSXA scanner at {self._scan_binary_url} during {method_type} scan. "
            f"Original error: {error_str}"
        )

    def _handle_http_error(self, error: httpx.HTTPStatusError, is_async: bool = False) -> Exception:
        """Convert HTTP status errors to more descriptive exceptions"""
        status_code = error.response.status_code
        method_type = "async" if is_async else "sync"

        try:
            response_body = error.response.text
        except:
            response_body = "Unable to read response body"

        if status_code == 400:
            return DSXAServiceError(
                f"DSXA scanner rejected the request (HTTP 400 Bad Request). "
                f"The file format or metadata may be invalid. "
                f"URL: {self._scan_binary_url}. Response: {response_body[:200]}"
            )
        elif status_code == 401:
            return DSXAServiceError(
                f"Authentication failed with DSXA scanner (HTTP 401 Unauthorized). "
                f"Please check API credentials. "
                f"URL: {self._scan_binary_url}"
            )
        elif status_code == 403:
            return DSXAServiceError(
                f"Access forbidden to DSXA scanner (HTTP 403 Forbidden). "
                f"Please check API permissions. "
                f"URL: {self._scan_binary_url}"
            )
        elif status_code == 404:
            return DSXAServiceError(
                f"DSXA scanner endpoint not found (HTTP 404 Not Found). "
                f"Please verify the scanner URL is correct. "
                f"URL: {self._scan_binary_url}"
            )
        elif status_code == 413:
            return DSXAServiceError(
                f"File too large for DSXA scanner (HTTP 413 Payload Too Large). "
                f"The file exceeds the maximum size limit. "
                f"URL: {self._scan_binary_url}"
            )
        elif status_code == 429:
            return DSXAServiceError(
                f"Rate limited by DSXA scanner (HTTP 429 Too Many Requests). "
                f"Please reduce scan frequency. "
                f"URL: {self._scan_binary_url}"
            )
        elif 500 <= status_code <= 599:
            return DSXAServiceError(
                f"DSXA scanner internal error (HTTP {status_code}). "
                f"The scanner service may be experiencing issues. "
                f"URL: {self._scan_binary_url}. Response: {response_body[:200]}"
            )
        else:
            return DSXAServiceError(
                f"Unexpected HTTP {status_code} error from DSXA scanner during {method_type} scan. "
                f"URL: {self._scan_binary_url}. Response: {response_body[:200]}"
            )

    def _prepare_request(self, scan_request: DSXAScanRequest) -> tuple[dict, bytes]:
        """Prepare headers and content for both sync and async requests."""
        headers = {}
        if scan_request.protected_entity:
            headers["protected_entity"] = scan_request.protected_entity
        if scan_request.metadata_info:
            # Clean metadata to ensure it's ASCII-safe
            clean_metadata = scan_request.metadata_info.encode("ascii", "ignore").decode("ascii")
            headers["X-Custom-Metadata"] = clean_metadata

        scan_request.binary_data.seek(0)  # Reset stream position
        content = scan_request.binary_data.read()

        return headers, content

    # ============================================================================
    # Synchronous Methods (for Celery tasks)
    # ============================================================================

    def scan_binary(self, scan_request: DSXAScanRequest) -> DPAVerdictModel2:
        """
        Synchronous binary scan - NO RETRY LOGIC.
        Let Celery handle retries with configurable policy.
        """
        try:
            headers, content = self._prepare_request(scan_request)
            file_size = len(content)

            dsx_logging.debug(f"Scanning {file_size} bytes with DSXA at {self._scan_binary_url}")

            response = self.sync_client.post(
                self._scan_binary_url,
                headers=headers,
                content=content
            )
            response.raise_for_status()
            verdict = response.json()
            return DPAVerdictModel2(**verdict)

        except httpx.ConnectError as e:
            raise self._handle_connection_error(e, is_async=False) from e
        except httpx.TimeoutException as e:
            raise DSXATimeoutError(
                f"DSXA scanner request timed out at {self._scan_binary_url}. "
                f"Try reducing file size or increasing timeout. Original error: {str(e)}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise self._handle_http_error(e, is_async=False) from e
        except httpx.RequestError as e:
            raise DSXAConnectionError(
                f"Request error during sync scan to DSXA at {self._scan_binary_url}. "
                f"Original error: {str(e)}"
            ) from e
        except Exception as e:
            error_str = str(e)
            if "json" in error_str.lower() or "decode" in error_str.lower():
                raise DSXAServiceError(
                    f"Invalid JSON response from DSXA scanner at {self._scan_binary_url}. "
                    f"The service may be returning an unexpected format. "
                    f"Original error: {error_str}"
                ) from e
            else:
                raise DSXAClientError(
                    f"Unexpected error during sync binary scan to {self._scan_binary_url}. "
                    f"Original error: {error_str}"
                ) from e

    def test_connection_sync(self) -> StatusResponse:
        """Synchronous connection test."""
        try:
            test_data = DSXAScanRequest(
                binary_data=io.BytesIO(b'This is a test file for connection verification'),
                metadata_info="connection-test"
            )
            self.scan_binary(scan_request=test_data)
            return StatusResponse(
                status=StatusResponseEnum.SUCCESS,
                message=f"Successfully connected to DSXA scanner at {self._scan_binary_url}"
            )
        except (DSXAConnectionError, DSXATimeoutError, DSXAServiceError, DSXAClientError) as e:
            dsx_logging.error(f"DSXA sync connection test failed: {str(e)}")
            return StatusResponse(
                status=StatusResponseEnum.ERROR,
                message=f"DSXA connection test failed: {str(e)}"
            )
        except Exception as e:
            dsx_logging.error(f"Unexpected error testing DSXA sync connection: {str(e)}")
            return StatusResponse(
                status=StatusResponseEnum.ERROR,
                message=f"Unexpected error testing DSXA connection: {str(e)}"
            )

    # ============================================================================
    # Async Methods (for concurrent operations)
    # ============================================================================

    async def _scan_binary_async_single(self, scan_request: DSXAScanRequest) -> DPAVerdictModel2:
        """
        Single async scan - NO RETRY LOGIC.
        This is the primitive used by scan_binaries_async.
        """
        try:
            headers, content = self._prepare_request(scan_request)
            file_size = len(content)

            dsx_logging.debug(f"Async scanning {file_size} bytes with DSXA at {self._scan_binary_url}")

            response = await self.async_client.post(
                self._scan_binary_url,
                headers=headers,
                content=content
            )

            response.raise_for_status()
            verdict = response.json()
            return DPAVerdictModel2(**verdict)

        except httpx.ConnectError as e:
            raise self._handle_connection_error(e, is_async=True) from e
        except httpx.TimeoutException as e:
            raise DSXATimeoutError(
                f"DSXA scanner async request timed out at {self._scan_binary_url}. "
                f"Try reducing file size or increasing timeout. Original error: {str(e)}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise self._handle_http_error(e, is_async=True) from e
        except httpx.RequestError as e:
            raise DSXAConnectionError(
                f"Request error during async scan to DSXA at {self._scan_binary_url}. "
                f"Original error: {str(e)}"
            ) from e
        except Exception as e:
            error_str = str(e)
            if "json" in error_str.lower() or "decode" in error_str.lower():
                raise DSXAServiceError(
                    f"Invalid JSON response from DSXA scanner at {self._scan_binary_url}. "
                    f"The service may be returning an unexpected format. "
                    f"Original error: {error_str}"
                ) from e
            else:
                raise DSXAClientError(
                    f"Unexpected error during async binary scan to {self._scan_binary_url}. "
                    f"Original error: {error_str}"
                ) from e

    async def scan_binaries_async(self, scan_requests: List[DSXAScanRequest]) -> List[DPAVerdictModel2]:
        """
        Async concurrent scanning - THIS IS WHERE ASYNC SHINES.
        Scans multiple files concurrently.
        """
        if not scan_requests:
            return []

        if len(scan_requests) == 1:
            # Single request - no need for gather overhead
            result = await self._scan_binary_async_single(scan_requests[0])
            return [result]

        # Multiple requests - run concurrently
        dsx_logging.info(f"Starting concurrent scan of {len(scan_requests)} files")
        tasks = [self._scan_binary_async_single(req) for req in scan_requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate successful results from exceptions
        successful_results = []
        failed_count = 0

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_count += 1
                dsx_logging.error(f"Scan {i+1} failed: {result}")
                # You might want to raise here or collect errors differently
                raise result  # Fail fast on first error
            else:
                successful_results.append(result)

        dsx_logging.info(f"Completed concurrent scan: {len(successful_results)} successful, {failed_count} failed")
        return successful_results

    async def scan_binary_async(self, scan_request: DSXAScanRequest) -> DPAVerdictModel2:
        """
        Single async scan - wrapper for compatibility.
        Note: This provides no async benefit over sync version.
        Use scan_binaries_async for true concurrency.
        """
        return await self._scan_binary_async_single(scan_request)

    async def test_connection_async(self) -> StatusResponse:
        """Async connection test."""
        try:
            test_data = DSXAScanRequest(
                binary_data=io.BytesIO(b'This is a test file for connection verification'),
                metadata_info="connection-test"
            )
            await self.scan_binary_async(scan_request=test_data)
            return StatusResponse(
                status=StatusResponseEnum.SUCCESS,
                message=f"Successfully connected to DSXA scanner at {self._scan_binary_url}"
            )
        except (DSXAConnectionError, DSXATimeoutError, DSXAServiceError, DSXAClientError) as e:
            dsx_logging.error(f"DSXA async connection test failed: {str(e)}")
            return StatusResponse(
                status=StatusResponseEnum.ERROR,
                message=f"DSXA connection test failed: {str(e)}"
            )
        except Exception as e:
            dsx_logging.error(f"Unexpected error testing DSXA async connection: {str(e)}")
            return StatusResponse(
                status=StatusResponseEnum.ERROR,
                message=f"Unexpected error testing DSXA connection: {str(e)}"
            )

    # ============================================================================
    # Legacy Methods with Retry (Optional, for backward compatibility)
    # ============================================================================

    async def scan_binary_async_with_retry(self, scan_request: DSXAScanRequest) -> DPAVerdictModel2:
        """
        Legacy async method with built-in retry.
        Only use if you need client-side retry for some reason.
        """
        if not self._enable_client_retry:
            return await self.scan_binary_async(scan_request)

        # Import retry here to make it optional
        from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            reraise=True,
            before_sleep=before_sleep_log(dsx_logging, log_level=logging.WARNING),
        )
        async def _scan_with_retry():
            return await self._scan_binary_async_single(scan_request)

        return await _scan_with_retry()


# ============================================================================
# Factory Functions
# ============================================================================

def create_dsxa_client(scan_binary_url: str, timeout: int = 600,
                       enable_client_retry: bool = False) -> DSXAClient:
    """
    Factory function to create DSXA client.

    Args:
        scan_binary_url: DSXA scanner endpoint URL
        timeout: Request timeout in seconds
        enable_client_retry: Enable client-side retry (usually should be False for Celery)
    """
    return DSXAClient(
        scan_binary_url=scan_binary_url,
        timeout=timeout,
        enable_client_retry=enable_client_retry
    )


# ============================================================================
# Usage Examples
# ============================================================================

if __name__ == "__main__":
    import time

    async def test_concurrent_scanning():
        """Demonstrate where async actually helps."""
        client = DSXAClient("http://localhost:8080/scan/binary/v2")

        # Create multiple test requests
        requests = [
            DSXAScanRequest(
                binary_data=io.BytesIO(f"Test file {i}".encode()),
                metadata_info=f"test-{i}"
            )
            for i in range(5)
        ]

        # Test sync (sequential)
        start = time.perf_counter()
        sync_results = []
        for req in requests:
            try:
                result = client.scan_binary(req)
                sync_results.append(result)
            except Exception as e:
                print(f"Sync scan failed: {e}")
        sync_time = time.perf_counter() - start

        # Test async (concurrent)
        start = time.perf_counter()
        try:
            async_results = await client.scan_binaries_async(requests)
        except Exception as e:
            print(f"Async scan failed: {e}")
            async_results = []
        async_time = time.perf_counter() - start

        print(f"Sync time (sequential): {sync_time:.2f}s")
        print(f"Async time (concurrent): {async_time:.2f}s")
        print(f"Speedup: {sync_time/async_time:.1f}x")

        await client.aclose()

    # Run test
    # asyncio.run(test_concurrent_scanning())
    print("DSXA Client optimized - run test_concurrent_scanning() to see async benefits")