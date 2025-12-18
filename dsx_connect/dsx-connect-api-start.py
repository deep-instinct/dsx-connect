# This file is part of DSX-Connect and is distributed under the terms of the
# GNU General Public License v3.0. See the top-level LICENSE file for details.

"""
A helper script to run the DSX-Connect FastAPI app (dsx_connect.app.dsx_connect_app) as a Uvicorn web application,
serving an API for scanning file paths and rendering verdicts.

The app provides a Swagger/Redoc UI at http://<host>:<port>/docs or can be accessed via any REST API client (e.g., Postman, cURL).
"""

import os
import sys
import pathlib
import uvicorn
from dsx_connect.config import get_config
from shared.dsx_logging import dsx_logging

# Add the distribution root (directory containing this script) to sys.path
dist_root = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(dist_root))

if __name__ == "__main__":
    cfg = get_config()
    try:
        dsx_logging.info(f"Results DB URL (DSXCONNECT_RESULTS_DB): {cfg.results_database.loc}")
        dsx_logging.info(f"Results retain (DSXCONNECT_RESULTS_DB__RETAIN): {cfg.results_database.retain}")
        dsx_logging.info(f"Registry Redis URL (DSXCONNECT_REDIS_URL): {cfg.redis_url}")
    except Exception:
        pass
    ssl_kwargs = {}
    if getattr(cfg, "use_tls", False) and cfg.tls_certfile and cfg.tls_keyfile:
        ssl_kwargs = {"ssl_certfile": cfg.tls_certfile, "ssl_keyfile": cfg.tls_keyfile}
    uvicorn.run(
        "dsx_connect.app.dsx_connect_api:app",
        host="0.0.0.0",
        port=8586,
        reload=False,  # Set to False in production with multiple workers
        workers=1,
        **ssl_kwargs
    )
