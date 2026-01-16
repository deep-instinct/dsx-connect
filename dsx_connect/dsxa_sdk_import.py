import sys
from pathlib import Path


def ensure_sdk_on_path() -> None:
    """
    Add the repo root to sys.path so the in-repo dsxa_sdk package can be imported
    without installing from PyPI.
    """
    root = Path(__file__).resolve().parents[1]
    sdk_pkg = root / "dsxa_sdk"

    for path in (sdk_pkg, root):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
