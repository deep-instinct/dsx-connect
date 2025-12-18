from pydantic import BaseModel
from enum import Enum

# these models are in here instead of the models module so that the dpa client can be used completely
class DPASeverityEnum(str, Enum):
    VERY_HIGH = 'VERY_HIGH'
    HIGH = 'HIGH'
    MEDIUM = 'MEDIUM'
    LOW = 'LOW'


class DPAVerdictEnum(str, Enum):
    UNKNOWN = 'Unknown'
    BENIGN = 'Benign'
    MALICIOUS = 'Malicious'
    UNSUPPORTED = 'Unsupported File Type'
    NOT_SCANNED = 'Not Scanned'


class DPAOfficeDataModel(BaseModel):
    vba: int
    swf: int
    load_external_object: int
    dde: int
    xl4_macros: int
    activex: int
    ole: int


class DPAVerdictModel(BaseModel):
    submit_time_in_milliseconds: int
    scan_guid: str | None = None
    file_type: str
    file_hash: str
    container_hash: str
    scan_duration_in_microseconds: int
    verdict: DPAVerdictEnum
    severity: DPASeverityEnum | None = None
    additional_office_data: DPAOfficeDataModel | None = None
    event_description: str


class DPAVerdictDetailsModel(BaseModel):
    event_description: str
    reason: str | None = None


class DPAVerdictFileInfoModel(BaseModel):
    file_type: str
    file_size_in_bytes: int
    file_hash: str | None = None
    additional_office_data: DPAOfficeDataModel | None = None


#
# {'scan_guid': '007ea79292ae4261ad82269cd13051b9',
# 'verdict': 'Benign',
# 'verdict_details':
#   {'event_description': 'File identified as benign'},
# 'file_info':
#   {'file_type': 'OOXMLFileType',
#   'file_size_in_bytes': 14844,
#   'file_hash': '286865e7337f30ac2d119d8edc9c36f6a11552eb23c50a1137a19e0ace921e8e',
#   'additional_office_data':
#       {'vba': 0, 'swf': 0, 'load_external_object': 0, 'dde': 0, 'xl4_macros': 0, 'activex': 0, 'ole': 0}},
# 'scan_duration_in_microseconds': 10404}]
class DPAVerdictModel2(BaseModel):
    scan_guid: str | None = None
    verdict: DPAVerdictEnum | None = None
    verdict_details: DPAVerdictDetailsModel | None = None
    file_info: DPAVerdictFileInfoModel | None = None
    scan_duration_in_microseconds: int = -1

