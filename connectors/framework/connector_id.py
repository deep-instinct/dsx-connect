import os
import uuid
from pathlib import Path

# Persist the UUID in a stable location relative to the app root (/app in containers),
# not the current working directory. This avoids duplicate UUIDs when CWD varies.
# Default: <app_root>/data/connector_uuid.txt (e.g., /app/data/connector_uuid.txt)
# Optional override: DSXCONNECTOR_DATA_DIR to point to a writable directory.

def _uuid_file_path() -> Path:
    app_root = Path(__file__).resolve().parents[2]  # .../connectors -> .../app or project root locally
    data_dir = Path(os.getenv("DSXCONNECTOR_DATA_DIR", str(app_root / "data")))
    return (data_dir / "connector_uuid.txt").resolve()


def get_or_create_connector_uuid() -> str:
    """
    Returns a stable UUID for the connector. If the UUID file exists, it reads and returns it.
    If the file is missing, it generates a new UUID, saves it, and returns it.
    """
    path = _uuid_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        return path.read_text().strip()

    new_uuid = str(uuid.uuid4())
    path.write_text(new_uuid)
    return new_uuid
