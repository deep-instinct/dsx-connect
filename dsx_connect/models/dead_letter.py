# Option 1: Use a string field with custom formatting
import time
from datetime import datetime, timezone
from typing import Union
from pydantic import BaseModel, Field, field_validator

from dsx_connect.models.connector_models import ScanRequestModel


class DeadLetterItem(BaseModel):
    scan_request: ScanRequestModel
    failure_reason: str
    error_details: str
    failed_at: str = Field(
        description="Formatted timestamp: YYYY-MM-DD HH:MM:SS UTC"
    )
    failed_at_timestamp: float = Field(
        default_factory=lambda: time.time(),
        description="Unix timestamp for calculations"
    )
    original_task_id: str
    retry_count: int

    @field_validator("failed_at", mode="before")
    @classmethod
    def format_timestamp(cls, v: Union[int, float, datetime, str, None]) -> str:
        """Convert any timestamp format to YYYY-MM-DD HH:MM:SS UTC"""
        if v is None:
            v = datetime.now(timezone.utc)

        if isinstance(v, str):
            # Assume it's already formatted correctly
            return v

        if isinstance(v, (int, float)):
            dt = datetime.fromtimestamp(v, timezone.utc)
        elif isinstance(v, datetime):
            # Ensure UTC
            if v.tzinfo is None:
                dt = v.replace(tzinfo=timezone.utc)
            else:
                dt = v.astimezone(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
