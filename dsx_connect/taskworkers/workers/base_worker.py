"""
Base worker implementation for DSX Connect Celery tasks.

This module defines a `BaseWorker` class that all Celery tasks should inherit
from when using Celery 5+.  It centralizes policy loading, retry/backoff
decisions, and Dead Letter Queue (DLQ) handling so that individual tasks
can focus on their business logic.  The `TaskContext` class captures
per-invocation metadata, and `RetryDecision` encapsulates whether a task
should retry and how long to wait before the next attempt.
"""

from __future__ import annotations

from enum import auto, Enum

from celery import Task, states
from celery.exceptions import Retry as CeleryRetry
from pydantic import ValidationError
from dsx_connect.taskworkers.errors import (
    TaskError, MalformedScanRequest,
    ConnectorConnectionError, ConnectorServerError, ConnectorClientError,
    DsxaTimeoutError, DsxaServerError, DsxaClientError,
)
from pydantic import ValidationError
from dsx_connect.taskworkers.policy import (
    load_policy,
    load_policy_variant,
    get_policy_info,
    RetryPolicy,
)
from dsx_connect.taskworkers.dlq_store import DeadLetterItem
from dsx_connect.taskworkers.errors import TaskError, MalformedScanRequest
from dsx_connect.config import get_config
from shared.dsx_logging import dsx_logging


class RetryDecision:
    """Represents the outcome of a retry decision.

    Attributes:
        should_retry: Whether the task should retry.
        backoff_seconds: Delay before the next attempt (only relevant if should_retry is True).
        reason: Short string describing why the retry or failure occurred.
    """

    def __init__(self, should_retry: bool, backoff_seconds: int = 0, reason: str = ""):
        self.should_retry = should_retry
        self.backoff_seconds = backoff_seconds
        self.reason = reason


class RetryGroup(Enum):
    CONNECTOR = auto()
    DSXA = auto()


class RetryGroups:
    @staticmethod
    def connector() -> set[RetryGroup]:
        return {RetryGroup.CONNECTOR}

    @staticmethod
    def dsxa() -> set[RetryGroup]:
        return {RetryGroup.DSXA}

    @staticmethod
    def connector_and_dsxa() -> set[RetryGroup]:
        return {RetryGroup.CONNECTOR, RetryGroup.DSXA}

    @staticmethod
    def all() -> set[RetryGroup]:
        return set(RetryGroup)

    @staticmethod
    def none() -> set[RetryGroup]:
        return set()

class TaskContext:
    """Holds per-execution metadata for a Celery task.

    A new context is created for each task invocation.  It captures
    the Celery-generated task ID, retry count, and the default retry policy
    determined from the application environment.  Policy information is
    logged on the first attempt for transparency.
    """

    def __init__(self, task_self: Task):
        # Unique identifier for this task invocation
        self.task_id = getattr(task_self.request, 'id', 'unknown')
        # Number of previous retries (0 on first attempt)
        self.retry_count = getattr(task_self.request, 'retries', 0)
        # Load the default policy for the current environment
        self.policy: RetryPolicy = load_policy()
        # Log policy info only on the first attempt
        if self.retry_count == 0:
            policy_info = get_policy_info(self.policy)
            dsx_logging.debug(f"[{self.task_id}] Policy: {policy_info}")


class BaseWorker(Task):
    """Base class for DSX Connect Celery tasks.

    Subclasses should override :meth:`execute` to implement the core business
    logic.  This base class handles retry/backoff logic via
    :meth:`_decide_retry_strategy` and DLQ submission via
    :meth:`_handle_final_failure`.  The :meth:`run` method sets up a
    :class:`TaskContext` and delegates to :meth:`execute`, catching any
    exceptions and either retrying or sending the task to the DLQ.
    """

    #: Optional DLQ queue name.  Subclasses may set this to override the
    #: default behaviour of constructing the DLQ queue name from the task name.
    dlq_queue_name: str | None = None
    RETRY_GROUPS: set[RetryGroup] = {RetryGroup.CONNECTOR}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Default the Celery task name to the class name unless explicitly set
        if not getattr(self, 'name', None):
            self.name = self.__class__.__name__

        self.context: TaskContext | None = None


    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------
    def execute(self, *args, **kwargs) -> str:
        """Override this method to perform the task's work.

        The default implementation raises NotImplementedError.
        """
        raise NotImplementedError("Subclasses must implement execute()")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run(self, *args, **kwargs):
        """Entry point for task execution (called by Celery).

        This method sets up a :class:`TaskContext`, loads any policy
        override, logs the attempt, invokes the business logic, and handles
        exceptions via retry or DLQ.
        """
        self.context = TaskContext(self)

        # Explicit chain root if provided by caller (we do not require it)
        self.context.scan_request_task_id = kwargs.get("scan_request_task_id")
        self.context.current_task_id = self.context.task_id

        # Extract an optional policy variant from the keyword arguments
        policy_override = kwargs.pop('policy_override', None)
        # Determine which retry policy to use
        if policy_override:
            policy = load_policy_variant(policy_override)
            dsx_logging.info(
                f"[{self.name}:{self.context.task_id}] Using policy variant: {policy_override}"
            )
        else:
            policy = self.context.policy
        # Log the current attempt (note: retries is 0-based)
        dsx_logging.info(
            f"[{self.name}:{self.context.task_id}] Processing "
            f"(attempt {self.context.retry_count + 1}/{policy.max_retries + 1}, env={policy.environment})"
        )
        try:
            # Delegate to the subclass's business logic
            result = self.execute(*args, **kwargs)
            dsx_logging.info(
                f"[{self.name}:{self.context.task_id}] Task completed successfully."
            )
            return result
        except CeleryRetry:
            # Let Celery handle retry scheduling; do not treat as failure
            raise
        except Exception as error:
            return self._handle_exception(error, policy, *args, **kwargs)

    # ------------------------------------------------------------------
    # Exception handling
    # ------------------------------------------------------------------
    def _handle_exception(self, error: Exception, policy: RetryPolicy, *args, **kwargs):
        """Determine whether to retry or send the task to the DLQ."""
        task_id = getattr(self.request, 'id', 'unknown')
        retry_count = getattr(self.request, 'retries', 0)
        decision = self._decide_retry_strategy(error, retry_count, policy)
        if decision.should_retry:
            dsx_logging.warning(
                f"[{self.name}:{task_id}] Retriable error ({decision.reason}): "
                f"retrying in {decision.backoff_seconds}s (attempt {retry_count + 1}/{policy.max_retries + 1})."
            )
            # Delegate retry to Celery, preserving the original exception
            raise self.retry(exc=error, countdown=decision.backoff_seconds)
        else:
            dsx_logging.error(
                f"[{self.name}:{task_id}] Final failure ({decision.reason}). Sending to DLQ."
            )
            self._handle_final_failure(error, decision.reason, *args, **kwargs)
            # Mark the task as failed for Celery monitoring
            # self.update_state(
            #     state=states.FAILURE,
            #     meta={
            #         "reason": decision.reason,
            #         "error": str(error),
            #         "error_type": error.__class__.__name__
            #     }
            # )
            # Return None to indicate task completion (failed)
            return None


    def _connector_mapping(self, policy):
        return [
            (ConnectorConnectionError, policy.retry_connector_connection_errors, policy.connector_backoff_base, "connector_connection"),
            (ConnectorServerError,     policy.retry_connector_server_errors,     policy.server_backoff_base,    "connector_server"),
            (ConnectorClientError,     policy.retry_connector_client_errors,     policy.connector_backoff_base, "connector_client"),
        ]

    def _dsxa_mapping(self, policy):
        return [
            (DsxaTimeoutError, policy.retry_dsxa_timeout_errors, policy.dsxa_backoff_base, "dsxa_timeout"),
            (DsxaServerError,  policy.retry_dsxa_server_errors,  policy.dsxa_backoff_base, "dsxa_server"),
            (DsxaClientError,  policy.retry_dsxa_client_errors,  policy.dsxa_backoff_base, "dsxa_client"),
        ]

    def _extra_retry_mapping(self, policy):
        """Hook for task-specific extras (override in subclasses if needed)."""
        return []

    def _build_retry_mapping(self, policy):
        mapping = []
        if RetryGroup.CONNECTOR in self.RETRY_GROUPS:
            mapping += self._connector_mapping(policy)
        if RetryGroup.DSXA in self.RETRY_GROUPS:
            mapping += self._dsxa_mapping(policy)
        mapping += self._extra_retry_mapping(policy)
        return mapping

    def _decide_retry_strategy(self, error: Exception, attempt: int, policy: RetryPolicy) -> RetryDecision:
        """Compute a retry decision based on the error type and policy."""
        # Never retry validation errors
        if isinstance(error, (MalformedScanRequest, ValidationError)):
            return RetryDecision(False, reason="validation_error")

        # Table-driven mapping for known error types
        for exc_type, allowed, base, tag in self._build_retry_mapping(policy):
            if isinstance(error, exc_type):
                if not allowed:
                    return RetryDecision(False, reason=f"{tag}_no_retry")
                if attempt >= policy.max_retries:
                    return RetryDecision(False, reason="max_retries_exceeded")
                backoff = policy.compute_backoff(attempt + 1, base)
                return RetryDecision(True, backoff, f"{tag}_retry")

        # TaskError fallback (for backwards compatibility)
        if isinstance(error, TaskError):
            if not error.retriable:
                return RetryDecision(False, reason=getattr(error, "reason", "task_error"))
            if attempt >= policy.max_retries:
                return RetryDecision(False, reason="max_retries_exceeded")
            backoff = policy.compute_backoff(attempt + 1, policy.server_backoff_base)
            return RetryDecision(True, backoff, getattr(error, "reason", "task_error_retry"))

        # Unknown error: don't retry by default
        dsx_logging.error(
            f"[{self.name}:{getattr(self.request, 'id', 'unknown')}] Unknown error: {error}",
            exc_info=True,
        )
        return RetryDecision(False, reason="unknown_error")

    def _handle_final_failure(self, error: Exception, reason: str, *args, **kwargs) -> None:
        """
        Gather common failure context, then delegate DLQ enqueue to subclass.
        Subclasses must implement `_enqueue_dlq(...)`.
        """
        current_task_id = getattr(self.request, "id", "unknown")
        retry_count     = getattr(self.request, "retries", 0)

        # explicit chain root; fall back to current if this is the root task
        scan_request_task_id = kwargs.get("scan_request_task_id") or current_task_id
        upstream_task_id     = kwargs.get("upstream_task_id")  # optional

        # Let the concrete worker decide how to shape the DLQ item
        self._enqueue_dlq(
            error=error,
            reason=reason,
            scan_request_task_id=scan_request_task_id,
            current_task_id=current_task_id,
            retry_count=retry_count,
            upstream_task_id=upstream_task_id,
            args=args,
            kwargs=kwargs,
        )

    def _enqueue_dlq(self, **_):  # pragma: no cover
        raise NotImplementedError("Subclasses must implement _enqueue_dlq(...)")
