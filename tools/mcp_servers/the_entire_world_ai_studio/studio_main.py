"""
The Entire World Tech Connector — modular application entry point.

Use this file to launch the studio after the architecture refactor.
The legacy the_entire_world_ai_studio.py remains as a compatibility shim
until it can be replaced.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.application import run_application

if __name__ == "__main__":
    run_application()
