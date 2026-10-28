from pathlib import Path
import re

from pydantic import Field, HttpUrl, SecretStr, model_validator
from connectors.framework.base_config import BaseConnectorConfig
from shared.models.connector_models import ItemActionEnum


class JiraConnectorConfig(BaseConnectorConfig):
    name: str = "jira-connector"
    platform: str = "jira"
    connector_url: HttpUrl = "http://localhost:8680"
    asset: str = Field(default="", description="Required JQL scope, e.g. project = TEST")
    capabilities: dict = Field(default_factory=lambda: {"write": False, "remediate": False, "monitor": False})
    jira_site_url: str = ""
    jira_cloud_id: str = ""
    jira_email: str = ""
    jira_api_token: SecretStr = SecretStr("")
    jira_api_token_file: str = ""
    jira_http_timeout: float = Field(default=60, gt=0)
    jira_page_size: int = Field(default=50, ge=1, le=100)
    monitor: bool = False
    jira_poll_interval_seconds: int = Field(default=30, ge=10)
    jira_checkpoint_file: str = "data/jira-monitor.sqlite3"
    jira_discover_spaces: bool = False
    jira_demo_mode: bool = False
    jira_demo_issue_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_demo_scope(self):
        self.jira_demo_issue_keys = list(dict.fromkeys(key.strip().upper() for key in self.jira_demo_issue_keys))
        if self.jira_demo_mode and not self.jira_demo_issue_keys:
            raise ValueError("Demo mode requires an explicit issue allowlist")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*-[0-9]+", key) for key in self.jira_demo_issue_keys):
            raise ValueError("Invalid issue key in demo allowlist")
        return self

    def demo_jql(self) -> str:
        if not self.jira_demo_mode:
            return ""
        if not self.jira_demo_issue_keys:
            raise ValueError("Demo issue allowlist is empty")
        return "key in (" + ",".join(self.jira_demo_issue_keys) + ")"

    @model_validator(mode="after")
    def read_only(self):
        if self.monitor and (self.register_with_core or not self.register_with_control_plane):
            raise ValueError("Jira polling requires DSX Connect 2 registration only")
        if self.item_action != ItemActionEnum.NOTHING:
            raise ValueError("Jira prototype supports only item_action=nothing")
        return self

    def token(self) -> str:
        if self.jira_api_token_file:
            return Path(self.jira_api_token_file).expanduser().read_text().strip()
        return self.jira_api_token.get_secret_value()
