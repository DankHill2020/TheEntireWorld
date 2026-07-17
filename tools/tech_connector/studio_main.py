"""
The Entire World Tech Connector — modular application entry point.

Use this file to launch the studio after the architecture refactor.
The app root is derived from this file so the launcher remains relocatable.
"""

import sys
from pathlib import Path

_ROOT = next(
    candidate for candidate in Path(__file__).resolve().parents if candidate.name.lower() == "tools"
)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tech_connector.app.application import run_application

if __name__ == "__main__":
    run_application()
