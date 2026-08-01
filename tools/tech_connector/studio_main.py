"""
The Entire World Tech Connector — modular application entry point.

Use this file to launch the studio after the architecture refactor.
The app root is derived from this file so the launcher remains relocatable.
"""

import sys
from pathlib import Path

from tech_connector.path_bootstrap import ensure_tools_root_on_path

ensure_tools_root_on_path(__file__)

from tech_connector.app.application import run_application

if __name__ == "__main__":
    run_application()
