from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil


def install_unity_bridge(project_path: str | Path) -> Path:
    project = Path(project_path).expanduser().resolve()
    if not (project / "Assets").is_dir() or not (project / "ProjectSettings").is_dir():
        raise ValueError(f"Not a Unity project directory: {project}")
    source = Path(__file__).resolve().parents[1] / "bridges" / "unity" / "TechConnectorBridge.cs"
    if not source.is_file():
        raise FileNotFoundError(f"Unity bridge source is missing: {source}")
    destination = project / "Assets" / "Editor" / "TechConnectorBridge.cs"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the Tech Connector Editor bridge in a Unity project.")
    parser.add_argument("project", nargs="?", default=os.environ.get("UNITY_PROJECT_PATH", ""))
    args = parser.parse_args()
    project = str(args.project or "").strip()
    if not project:
        project = input("Unity project directory: ").strip().strip('"')
    try:
        destination = install_unity_bridge(project)
    except Exception as exc:
        print(f"Unity bridge install failed: {exc}")
        return 1
    print(f"Installed Unity bridge: {destination}")
    print("Return to Unity and wait for the Editor script compilation to finish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
