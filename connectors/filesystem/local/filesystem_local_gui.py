#!/usr/bin/env python3
"""GUI wrapper for filesystem local runtime manager."""

from __future__ import annotations

import connectors.filesystem.local.filesystem_local as manager
from connectors.framework.local_gui import SingleServiceLocalGui


def main() -> None:
    SingleServiceLocalGui(
        manager=manager,
        title="Filesystem Connector Local",
        state_dir=manager.DEFAULT_STATE_DIR,
        port=manager.DEFAULT_PORT,
    ).run()


if __name__ == "__main__":
    main()
