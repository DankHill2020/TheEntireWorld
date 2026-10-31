"""Disposable persistent Unreal HTTP bridge for headless pipeline benchmarks.

This commandlet script explicitly pumps the existing Unreal request queue on
the commandlet's main thread because a headless commandlet has no Slate tick.
It is a benchmark helper, not a replacement for the interactive editor host.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from unreal_tools import http_server


proof_root = Path(os.environ["TECH_CONNECTOR_UNREAL_PROOF_ROOT"])
stop_file = proof_root / "stop_unreal_persistent_host.txt"
http_server._write_port_files = lambda port: None  # leave normal user port discovery untouched
http_server.start_http_server_in_thread()
deadline = time.monotonic() + 240
while not stop_file.exists() and time.monotonic() < deadline:
    http_server.tick(0.0)
    time.sleep(0.01)
