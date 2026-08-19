"""Discover and run first-time DCC installer launchers."""

from __future__ import annotations

import glob
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from tech_connector.models.constants import APP_ROOT, TOOLS_ROOT


@dataclass(frozen=True)
class DCCInstallerLauncher:
    app_id: str
    display_name: str
    marker: str
    script_path: Path
    executable_path: Path
    version: str = ""


def _glob_paths(patterns: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(Path(path) for path in glob.glob(pattern))
    return sorted(set(paths), key=lambda path: str(path).lower())


def _version_from_path(path: Path, pattern: str) -> str:
    match = re.search(pattern, str(path), re.IGNORECASE)
    return match.group(1) if match else ""


def discover_first_run_dcc_installers(
    tools_root: Path | None = None,
    app_root: Path | None = None,
) -> list[DCCInstallerLauncher]:
    """Return installer launchers for installed DCC apps with available scripts."""
    tools_root = Path(tools_root or TOOLS_ROOT)
    app_root = Path(app_root or APP_ROOT)
    launchers: list[DCCInstallerLauncher] = []

    for executable in _glob_paths([r"C:\Program Files\Autodesk\Maya*\bin\maya.exe"]):
        version = _version_from_path(executable, r"Maya(\d{4})")
        script = tools_root / "maya_tools" / f"run_maya_with_setup_{version}.bat"
        if version and script.exists():
            launchers.append(
                DCCInstallerLauncher(
                    app_id="maya",
                    display_name=f"Maya {version}",
                    marker=f"maya_{version}",
                    script_path=script,
                    executable_path=executable,
                    version=version,
                )
            )

    motionbuilder_patterns = [
        r"C:\Program Files\Autodesk\MotionBuilder*\bin\x64\motionbuilder.exe",
        r"C:\Program Files\Autodesk\MotionBuilder*\bin\motionbuilder.exe",
    ]
    for executable in _glob_paths(motionbuilder_patterns):
        version = _version_from_path(executable, r"MotionBuilder\s*(\d{4})")
        script = tools_root / "motionbuilder_tools" / f"run_motionbuilder_with_setup_{version}.bat"
        if version and script.exists():
            launchers.append(
                DCCInstallerLauncher(
                    app_id="motionbuilder",
                    display_name=f"MotionBuilder {version}",
                    marker=f"motionbuilder_{version}",
                    script_path=script,
                    executable_path=executable,
                    version=version,
                )
            )

    blender_exes = _glob_paths(
        [
            r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        ]
    )
    blender_script = app_root / "installers" / "Install_Blender_AI_Studio_Bridge.bat"
    if blender_exes and blender_script.exists():
        launchers.append(
            DCCInstallerLauncher(
                app_id="blender",
                display_name="Blender",
                marker="blender",
                script_path=blender_script,
                executable_path=blender_exes[-1],
            )
        )

    return launchers


def run_installer_launcher(
    launcher: DCCInstallerLauncher,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> None:
    """Start a launcher .bat without blocking the UI."""
    env = dict(os.environ)
    env["AI_STUDIO_NONINTERACTIVE"] = "1"
    if os.name == "nt":
        popen(
            ["cmd", "/c", str(launcher.script_path)],
            cwd=str(launcher.script_path.parent),
            env=env,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        popen(
            [str(launcher.script_path)],
            cwd=str(launcher.script_path.parent),
            env=env,
            close_fds=True,
        )


def pending_first_time_dcc_installers(settings: dict) -> list[DCCInstallerLauncher]:
    """Return discovered installers that have not been accepted/run before."""
    seen = set(settings.get("dcc_bridge_setup_seen", []))
    return [
        launcher
        for launcher in discover_first_run_dcc_installers()
        if launcher.marker not in seen
    ]


def run_first_time_dcc_installers(
    settings: dict,
    save_settings: Callable[[], None],
    launchers: Iterable[DCCInstallerLauncher] | None = None,
) -> list[DCCInstallerLauncher]:
    """Run each discovered installer once, tracked in dcc_bridge_setup_seen."""
    seen = set(settings.get("dcc_bridge_setup_seen", []))
    launched: list[DCCInstallerLauncher] = []
    for launcher in list(launchers) if launchers is not None else discover_first_run_dcc_installers():
        if launcher.marker in seen:
            continue
        run_installer_launcher(launcher)
        seen.add(launcher.marker)
        launched.append(launcher)

    if launched:
        settings["dcc_bridge_setup_seen"] = sorted(seen)
        save_settings()
    return launched
