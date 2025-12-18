from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl, Field


class ItemActionEnum(str, Enum):
    NOT_IMPLEMENTED = 'not implemented'
    NOTHING = 'nothing'
    DELETE = 'delete'
    MOVE = 'move'
    TAG = 'tag'
    MOVE_TAG = 'movetag'


class ItemActionModel(BaseModel):
    action_type: ItemActionEnum = ItemActionEnum.NOTHING
    action_meta: str = None


class ConnectorStatusEnum(str, Enum):
    READY: str = 'ready'
    STARTING: str = 'starting'
    STOPPED: str = 'stopped'
    FAILED_INIT: str = 'failed'


class ConnectorInstanceModel(BaseModel):
    name: str = 'connector'
    display_name: str | None = None
    display_icon: str | None = None
    uuid: UUID | None = None
    meta_info: str | None = None
    url: str = ''
    status: ConnectorStatusEnum = ConnectorStatusEnum.STARTING
    item_action_move_metainfo: str = ''
    asset: str = ''
    # Optional human-friendly label for asset path
    asset_display_name: str | None = None
    filter: str = ''
    last_repo_check_ts: Optional[float] = None
    last_repo_check_reason: Optional[str] = None   # e.g., "auth_failure", "bucket_not_found"
    last_repo_check_message: Optional[str] = None  # human-readable


class ScanRequestModel(BaseModel):
    connector: ConnectorInstanceModel = None
    location: str
    metainfo: str
    connector_url: str = None
    # Logical job identifier to associate related scan requests.
    # For connector full scans, all enqueued items share a job id.
    # For single events (e.g., webhook), a unique job id represents a job of one.
    scan_job_id: str | None = None
