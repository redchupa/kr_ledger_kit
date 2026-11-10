"""Make the pure-python parser importable without Home Assistant."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "kr_ledger"))
sys.path.insert(0, str(ROOT))
