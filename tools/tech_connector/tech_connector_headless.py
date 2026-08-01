"""Package-level command-line entry point for Tech Connector headless workflows."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = Path(__file__).resolve().parent / "scripts" / "tech_connector_headless.py"

if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))


if __name__ == "__main__":
    runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
else:
    from tech_connector.scripts.tech_connector_headless import run_pipeline

    __all__ = ["run_pipeline"]
