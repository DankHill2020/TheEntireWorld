"""Smoke tests for staged or frozen Tech Connector package payloads."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def smoke_import(package_root: Path) -> None:
    env = dict(os.environ)
    env["AI_STUDIO_TOOLS_ROOT"] = str(package_root)
    code = (
        "import os, sys; "
        "sys.path.insert(0, os.environ['AI_STUDIO_TOOLS_ROOT']); "
        "import tech_connector; "
        "from tech_connector.models.constants import APP_ROOT, TOOLS_ROOT, APP_VERSION; "
        "from tech_connector.app.application import run_application; "
        "print('import_ok', APP_VERSION, APP_ROOT, TOOLS_ROOT)"
    )
    subprocess.run([sys.executable, "-c", code], cwd=str(package_root), env=env, check=True)


def smoke_frozen_exe(exe_path: Path, timeout: float) -> None:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = env.get("QT_QPA_PLATFORM", "offscreen")
    env["TECH_CONNECTOR_SMOKE_TEST"] = "1"
    env["AI_STUDIO_SKIP_SPLASH"] = "1"
    proc = subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent), env=env)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("frozen_launch_ok timeout_terminated")
        return
    if proc.returncode not in (0, None):
        raise SystemExit(f"Frozen executable exited with code {proc.returncode}")
    print("frozen_launch_ok exited")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test staged or frozen Tech Connector packages.")
    parser.add_argument("path", help="Path to staged package root or frozen TechConnector.exe.")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    path = Path(args.path).resolve()
    if path.is_file() and path.suffix.lower() == ".exe":
        smoke_frozen_exe(path, args.timeout)
    else:
        smoke_import(path)


if __name__ == "__main__":
    main()
