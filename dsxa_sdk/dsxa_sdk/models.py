from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class VerdictEnum(str, Enum):
    BENIGN = "Benign"
    MALICIOUS = "Malicious"
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
    container_files_scanned: Optional[int] = None
    container_files_scanned_size: Optional[int] = None
    x_custom_metadata: Optional[str] = Field(None, alias="X-Custom-Metadata")
    last_update_time: Optional[str] = None

    class Config:
        populate_by_name = True


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
