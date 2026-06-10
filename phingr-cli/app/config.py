"""Configuration via environment variables."""

import os
from pathlib import Path

PHINGR_DEVICE_URL = os.environ.get("PHINGR_DEVICE_URL", "http://localhost:8080")
DATA_DIR = Path(os.environ.get("PHINGR_DATA_DIR", Path(__file__).parent.parent / "data"))
FLOWS_DIR = DATA_DIR / "flows"

# Ensure data dirs exist
FLOWS_DIR.mkdir(parents=True, exist_ok=True)
