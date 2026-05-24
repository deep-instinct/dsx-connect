from __future__ import annotations


class TerminalWorkerError(RuntimeError):
    """Non-retryable worker failure that should be recorded and sent to DLQ."""
