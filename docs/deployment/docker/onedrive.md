# OneDrive Connector — Docker Compose

Use `connectors/onedrive/deploy/docker/docker-compose-onedrive-connector.yaml` as the base manifest. Provide the OneDrive app credentials and target folder (`SP_*` equivalents become `ONEDRIVE_*`). The connector mirrors the SharePoint workflow: it registers with dsx-connect, handles full scans, and triggers delta sync from Microsoft Graph webhooks when enabled. For `ONEDRIVE_ASSET`, browse to the folder in OneDrive, note its path (e.g., `/Documents/dsx-connect`), and supply that drive-relative string.
