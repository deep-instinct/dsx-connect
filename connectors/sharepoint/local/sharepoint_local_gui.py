#!/usr/bin/env python3
"""GUI wrapper for SharePoint local runtime manager."""

from __future__ import annotations

import connectors.sharepoint.local.sharepoint_local as manager
from connectors.framework.local_gui import SingleServiceLocalGui


def main() -> None:
    SingleServiceLocalGui(
        manager=manager,
        title="SharePoint Connector Local",
        state_dir=manager.DEFAULT_STATE_DIR,
        port=manager.DEFAULT_PORT,
        env_fields=[
            ("SP_TENANT_ID", "DSXCONNECTOR_SP_TENANT_ID", False),
            ("SP_CLIENT_ID", "DSXCONNECTOR_SP_CLIENT_ID", False),
            ("SP_CLIENT_SECRET", "DSXCONNECTOR_SP_CLIENT_SECRET", True),
            ("SP_WEBHOOK_ENABLED", "DSXCONNECTOR_SP_WEBHOOK_ENABLED", False),
            ("SP_WEBHOOK_URL", "DSXCONNECTOR_WEBHOOK_URL", False),
        ],
        require_init_before_start=True,
        env_edit_dev_only=True,
    ).run()


if __name__ == "__main__":
    main()
