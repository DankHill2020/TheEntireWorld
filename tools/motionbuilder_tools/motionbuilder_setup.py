from __future__ import annotations

"""Explicit, bounded bootstrap for the current MotionBuilder installation."""

import importlib.util
from pathlib import Path
import subprocess

import pyfbsdk as fb


def get_motionbuilder_version_string() -> str:
    version_number = int(fb.FBSystem().Version)
    major = version_number // 1000
    return f"MotionBuilder 20{major}"


def motionbuilder_python_path() -> Path:
    return Path("C:/Program Files/Autodesk") / get_motionbuilder_version_string() / "bin/x64/python/python.exe"


def _requests_available() -> bool:
    return importlib.util.find_spec("requests") is not None


def install_current_motionbuilder_tools(*, timeout_seconds: float = 120.0) -> dict[str, object]:
    """Ensure the bridge dependency exists without mutating the host on import."""

    python = motionbuilder_python_path()
    if _requests_available():
        return {
            "status": "ready",
            "changed": False,
            "python": str(python),
            "message": "MotionBuilder Python already provides requests.",
        }
    if not python.is_file():
        raise FileNotFoundError(f"MotionBuilder Python was not found: {python}")
    timeout = max(1.0, min(600.0, float(timeout_seconds)))
    commands = (
        [str(python), "-m", "ensurepip", "--upgrade"],
        [str(python), "-m", "pip", "install", "requests"],
    )
    diagnostics: list[str] = []
    for command in commands:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        diagnostics.extend(
            text.strip() for text in (completed.stdout, completed.stderr) if text.strip()
        )
        if completed.returncode != 0:
            detail = diagnostics[-1] if diagnostics else "No installer diagnostics were returned."
            raise RuntimeError(f"MotionBuilder dependency setup failed: {detail}")
    return {
        "status": "ready",
        "changed": True,
        "python": str(python),
        "message": "Installed the missing requests dependency.",
        "diagnostics": diagnostics[-4:],
    }


if __name__ == "__main__":
    result = install_current_motionbuilder_tools()
    print(result["message"])


__all__ = [
    "get_motionbuilder_version_string",
    "install_current_motionbuilder_tools",
    "motionbuilder_python_path",
]
