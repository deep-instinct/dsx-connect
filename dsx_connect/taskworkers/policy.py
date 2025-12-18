from __future__ import annotations
import dataclasses
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from dsx_connect.config import get_config, AppEnv


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int
    connector_backoff_base: int
    dsxa_backoff_base: int
    server_backoff_base: int
    retry_connector_connection_errors: bool
    retry_connector_server_errors: bool
    retry_connector_client_errors: bool
    retry_dsxa_connection_errors: bool
    retry_dsxa_timeout_errors: bool
    retry_dsxa_server_errors: bool
    retry_dsxa_client_errors: bool

    # Meta information about the policy
    environment: str = "default"
    description: str = "Standard retry policy"

    def compute_backoff(self, attempt: int, base: int) -> int:
        """Exponential backoff with cap."""
        delay = base * (2 ** (attempt - 1))
        return min(delay, 60 * 5)  # cap at 5 minutes


@lru_cache
def load_base_policy() -> RetryPolicy:
    """Load base retry policy from configuration."""
    c = get_config().workers
    return RetryPolicy(
        max_retries=c.scan_request_max_retries,
        connector_backoff_base=c.connector_retry_backoff_base,
        dsxa_backoff_base=c.dsxa_retry_backoff_base,
        server_backoff_base=c.server_error_retry_backoff_base,
        retry_connector_connection_errors=c.retry_connector_connection_errors,
        retry_connector_server_errors=c.retry_connector_server_errors,
        retry_connector_client_errors=c.retry_connector_client_errors,
        retry_dsxa_connection_errors=c.retry_dsxa_connection_errors,
        retry_dsxa_timeout_errors=c.retry_dsxa_timeout_errors,
        retry_dsxa_server_errors=c.retry_dsxa_server_errors,
        retry_dsxa_client_errors=c.retry_dsxa_client_errors,
        environment="base",
        description="Base policy from configuration"
    )


def create_dev_policy(base: RetryPolicy) -> RetryPolicy:
    """Development environment: Fast feedback, minimal delays."""
    return dataclasses.replace(base,
                               # Fast retries for quick feedback during development
                               max_retries=1,  # Fail fast, don't waste time
                               connector_backoff_base=5,  # 5 second base instead of 60
                               dsxa_backoff_base=3,       # 3 second base instead of 2
                               server_backoff_base=5,     # 5 second base instead of 30

                               # More lenient - retry client errors to see what's happening
                               retry_connector_client_errors=True,
                               retry_dsxa_client_errors=True,

                               environment="dev",
                               description="Development: fast feedback, lenient retries"
                               )


def create_staging_policy(base: RetryPolicy) -> RetryPolicy:
    """Staging environment: Production-like but with more debugging."""
    return dataclasses.replace(base,
                               # Similar to prod but with more retries for debugging
                               max_retries=3,  # More than dev, less than prod

                               # Moderate backoff - not too fast, not too slow
                               connector_backoff_base=30,  # Half of production
                               server_backoff_base=15,     # Half of production

                               # Retry client errors in staging to debug integration issues
                               retry_connector_client_errors=True,
                               retry_dsxa_client_errors=True,

                               environment="staging",
                               description="Staging: production-like with debugging features"
                               )


def create_prod_policy(base: RetryPolicy) -> RetryPolicy:
    """Production environment: Resilient, conservative."""
    return dataclasses.replace(base,
                               # Maximum resilience
                               max_retries=5,  # Full retry attempts

                               # Use configured backoff times (likely longer)
                               # connector_backoff_base, dsxa_backoff_base from config

                               # Conservative - don't retry client errors by default in prod
                               retry_connector_client_errors=False,  # 4xx usually means bad request
                               retry_dsxa_client_errors=False,       # Don't waste cycles on bad requests

                               environment="prod",
                               description="Production: maximum resilience, conservative retries"
                               )


def create_test_policy(base: RetryPolicy) -> RetryPolicy:
    """Test environment: Deterministic, fast, no retries."""
    return dataclasses.replace(base,
                               # No retries in tests - fail fast and predictably
                               max_retries=0,
                               connector_backoff_base=1,
                               dsxa_backoff_base=1,
                               server_backoff_base=1,

                               # Don't retry anything in tests
                               retry_connector_connection_errors=False,
                               retry_connector_server_errors=False,
                               retry_connector_client_errors=False,
                               retry_dsxa_connection_errors=False,
                               retry_dsxa_timeout_errors=False,
                               retry_dsxa_server_errors=False,
                               retry_dsxa_client_errors=False,

                               environment="test",
                               description="Test: no retries, deterministic behavior"
                               )


@lru_cache
def load_policy(env: Optional[AppEnv] = None) -> RetryPolicy:
    """
    Load environment-appropriate retry policy.

    Args:
        env: Environment override. If None, uses current app environment.

    Returns:
        RetryPolicy configured for the specified environment.
    """
    if env is None:
        env = get_config().app_env

    base = load_base_policy()

    if env == AppEnv.dev:
        return create_dev_policy(base)
    elif env == AppEnv.stg:
        return create_staging_policy(base)
    elif env == AppEnv.prod:
        return create_prod_policy(base)
    else:  # test or unknown
        return create_test_policy(base)


def load_policy_variant(variant: str) -> RetryPolicy:
    """
    Load named policy variants for special use cases.

    Args:
        variant: Named policy variant.

    Returns:
        RetryPolicy for the specified variant.
    """
    base = load_base_policy()

    if variant == "high_throughput":
        # For batch processing - fail fast, don't slow down the pipeline
        return dataclasses.replace(base,
                                   max_retries=0,
                                   retry_connector_connection_errors=False,
                                   retry_connector_server_errors=False,
                                   retry_dsxa_timeout_errors=False,
                                   retry_dsxa_server_errors=False,
                                   environment="high_throughput",
                                   description="High throughput: no retries, maximum speed"
                                   )

    elif variant == "critical_files":
        # For important files - maximum resilience
        return dataclasses.replace(base,
                                   max_retries=10,  # Really try hard
                                   connector_backoff_base=120,  # Longer backoff
                                   dsxa_backoff_base=60,
                                   server_backoff_base=90,
                                   # Retry everything
                                   retry_connector_connection_errors=True,
                                   retry_connector_server_errors=True,
                                   retry_connector_client_errors=True,
                                   retry_dsxa_connection_errors=True,
                                   retry_dsxa_timeout_errors=True,
                                   retry_dsxa_server_errors=True,
                                   retry_dsxa_client_errors=True,
                                   environment="critical_files",
                                   description="Critical files: maximum retries and resilience"
                                   )

    elif variant == "circuit_breaker":
        # When services are degraded - minimal retries
        return dataclasses.replace(base,
                                   max_retries=1,
                                   connector_backoff_base=300,  # 5 minute backoff
                                   dsxa_backoff_base=300,
                                   server_backoff_base=300,
                                   environment="circuit_breaker",
                                   description="Circuit breaker: minimal retries with long backoff"
                                   )

    else:
        # Unknown variant - return environment policy
        return load_policy()


def get_policy_info(policy: RetryPolicy) -> dict:
    """Get human-readable policy information for logging/debugging."""
    return {
        "environment": policy.environment,
        "description": policy.description,
        "max_retries": policy.max_retries,
        "backoff_bases": {
            "connector": policy.connector_backoff_base,
            "dsxa": policy.dsxa_backoff_base,
            "server": policy.server_backoff_base,
        },
        "retry_flags": {
            "connector_connection": policy.retry_connector_connection_errors,
            "connector_server": policy.retry_connector_server_errors,
            "connector_client": policy.retry_connector_client_errors,
            "dsxa_connection": policy.retry_dsxa_connection_errors,
            "dsxa_timeout": policy.retry_dsxa_timeout_errors,
            "dsxa_server": policy.retry_dsxa_server_errors,
            "dsxa_client": policy.retry_dsxa_client_errors,
        }
    }


# Usage examples:
if __name__ == "__main__":
    from shared.dsx_logging import dsx_logging

    # Default policy (uses current environment)
    policy = load_policy()
    dsx_logging.info(f"Loaded policy: {get_policy_info(policy)}")

    # Explicit environment policies
    dev_policy = load_policy(AppEnv.dev)
    prod_policy = load_policy(AppEnv.prod)

    # Special variants
    batch_policy = load_policy_variant("high_throughput")
    critical_policy = load_policy_variant("critical_files")

    print(f"Dev max retries: {dev_policy.max_retries}")
    print(f"Prod max retries: {prod_policy.max_retries}")
    print(f"Batch max retries: {batch_policy.max_retries}")
    print(f"Critical max retries: {critical_policy.max_retries}")