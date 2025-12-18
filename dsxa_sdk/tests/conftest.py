import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[1] / "dsxa_sdk"
if PKG_DIR.exists():
    sys.path.insert(0, str(PKG_DIR))
