from connectors.framework.base_config import BaseConnectorConfig


def test_control_plane_setting_names_are_read(monkeypatch) -> None:
    monkeypatch.setenv("DSXCONNECTOR_REGISTER_WITH_CONTROL_PLANE", "true")
    monkeypatch.setenv("DSXCONNECTOR_PLATFORM", "s3")
    monkeypatch.setenv("DSXCONNECTOR_PLATFORM_KEY", "aws-123")
    monkeypatch.setenv("DSXCONNECTOR_INTEGRATION_ID", "int_a")
    monkeypatch.setenv("DSXCONNECTOR_CONNECTOR_LABELS", '{"env": "lab"}')
    monkeypatch.setenv("DSXCONNECTOR_CAPABILITIES", '{"write": true}')
    monkeypatch.setenv("DSXCONNECTOR_LEASE_SECONDS", "90")
    monkeypatch.setenv("DSXCONNECTOR_DSX_CONNECT_V2_URL", "http://dsx-connect-api:8091")

    config = BaseConnectorConfig()

    assert config.register_with_control_plane is True
    assert config.platform == "s3"
    assert config.platform_key == "aws-123"
    assert config.integration_id == "int_a"
    assert config.connector_labels == {"env": "lab"}
    assert config.capabilities == {"write": True}
    assert config.lease_seconds == 90
    assert str(config.dsx_connect_v2_url) == "http://dsx-connect-api:8091/"


def test_connector_config_subclass_reads_control_plane_settings(monkeypatch) -> None:
    from connectors.aws_s3.config import AWSS3ConnectorConfig

    monkeypatch.setenv("DSXCONNECTOR_PLATFORM_KEY", "aws-123")

    assert AWSS3ConnectorConfig().platform_key == "aws-123"
