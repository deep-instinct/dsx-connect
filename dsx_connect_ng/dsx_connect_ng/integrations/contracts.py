from pydantic import BaseModel


class IntegrationCapabilities(BaseModel):
    discover: bool = True
    monitor: bool = True
    enumerate: bool = False
    read: bool = False
    remediate: bool = False


class IntegrationContract(BaseModel):
    platform: str
    capabilities: IntegrationCapabilities
