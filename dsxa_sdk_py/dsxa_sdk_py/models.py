from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator


class VerdictEnum(str, Enum):
    BENIGN = "Benign"
    MALICIOUS = "Malicious"
    UNKNOWN = "Unknown"
    UNSUPPORTED = "Unsupported File Type"
    NOT_SCANNED = "Not Scanned"
    SCANNING = "Scanning"
    NON_COMPLIANT = "Non Compliant"


class ThreatType(str, Enum):
    RANSOMWARE = "RANSOMWARE"
    BACKDOOR = "BACKDOOR"
    DROPPER = "DROPPER"
    PUA = "PUA"
    SPYWARE = "SPYWARE"
    VIRUS = "VIRUS"
    WORM = "WORM"
    DUALUSE = "DUALUSE"


class VerdictDetails(BaseModel):
    event_description: Optional[str] = Field(None, alias="event_description")
    reason: Optional[str] = None
    threat_type: Optional[ThreatType] = None

    class Config:
        populate_by_name = True


class FileInfo(BaseModel):
    file_type: Optional[str] = None
    file_size_in_bytes: Optional[int] = None
    file_hash: Optional[str] = None
    container_hash: Optional[str] = None
    additional_office_data: Optional[Dict[str, Any]] = None


class ScanResponse(BaseModel):
    scan_guid: str
    verdict: VerdictEnum
    verdict_details: VerdictDetails = Field(default_factory=VerdictDetails)
    file_info: Optional[FileInfo] = None
    protected_entity: Optional[int] = None
    scan_duration_in_microseconds: Optional[int] = None
    dsxconnect_request_elapsed_ms: Optional[float] = None
    dsxconnect_read_elapsed_ms: Optional[float] = None
    dsxconnect_dsxa_elapsed_ms: Optional[float] = None
    container_files_scanned: Optional[int] = None
    container_files_scanned_size: Optional[int] = None
    x_custom_metadata: Optional[str] = Field(None, alias="X-Custom-Metadata")
    last_update_time: Optional[str] = None

    class Config:
        populate_by_name = True

    @model_validator(mode="before")
    @classmethod
    def normalize_nested_dsxa_response(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        details = value.get("details")
        if not isinstance(details, dict):
            return value
        normalized = dict(value)
        if "verdict_details" not in normalized and "verdictDetails" in details:
            normalized["verdict_details"] = details.get("verdictDetails")
        if "file_info" not in normalized and "fileInfo" in details:
            normalized["file_info"] = details.get("fileInfo")
        if "container_files_scanned" not in normalized and "containerFilesScanned" in details:
            normalized["container_files_scanned"] = details.get("containerFilesScanned")
        if "container_files_scanned_size" not in normalized and "containerFilesScannedSize" in details:
            normalized["container_files_scanned_size"] = details.get("containerFilesScannedSize")
        if "X-Custom-Metadata" not in normalized and "xCustomMetadata" in details:
            normalized["X-Custom-Metadata"] = details.get("xCustomMetadata")
        if "last_update_time" not in normalized and "lastUpdateTime" in details:
            normalized["last_update_time"] = details.get("lastUpdateTime")
        return normalized


class ScanByPathResponse(BaseModel):
    scan_guid: str
    verdict: VerdictEnum
    verdict_details: VerdictDetails = Field(default_factory=VerdictDetails)
    file_info: Optional[FileInfo] = None
    x_custom_metadata: Optional[str] = Field(None, alias="X-Custom-Metadata")

    class Config:
        populate_by_name = True


class ScanByPathVerdictResponse(ScanResponse):
    """Identical schema to ScanResponse but kept for clarity."""


class HashScanResponse(ScanResponse):
    """Alias for scan-by-hash payloads."""
