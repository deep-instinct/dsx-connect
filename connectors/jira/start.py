import uvicorn
import connectors.jira.jira_connector  # noqa: F401

if __name__ == "__main__":
    uvicorn.run("connectors.framework.dsx_connector:connector_api", host="0.0.0.0", port=8680)
