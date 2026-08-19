"""Explicit, idempotent Maya commandPort/Live Link bootstrap installer."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Iterable


BOOTSTRAP_VERSION = "2"
BLOCK_BEGIN = "# BEGIN Tech Connector Maya Bridge (managed)"
BLOCK_END = "# END Tech Connector Maya Bridge (managed)"

LEGACY_MAYA_USER_SETUP_CODE = r"""# Tech Connector Maya Live Link Startup Script
import sys
import os
import maya.cmds as cmds
import maya.api.OpenMaya as om

def _init_tech_connector_livelink():
    port = int(os.environ.get("MAYA_COMMAND_PORT", "7001"))
    port_name = f":{port}"
    try:
        if not cmds.commandPort(port_name, q=True):
            cmds.commandPort(name=port_name, sourceType="python", echoOutput=True, noreturn=False)
            print(f"[Tech Connector] Maya Live Link commandPort open on port {port}")
    except Exception as exc:
        print(f"[Tech Connector] commandPort init note: {exc}")

    # Auto-load official Autodesk Maya Live Link Plugin if present
    try:
        if not cmds.pluginInfo("MayaLiveLinkPlugin", q=True, loaded=True):
            cmds.loadPlugin("MayaLiveLinkPlugin", quiet=True)
            print("[Tech Connector] Loaded MayaLiveLinkPlugin successfully.")
    except Exception:
        pass

# Schedule initialization after Maya UI is ready
cmds.evalDeferred(_init_tech_connector_livelink)
"""

MAYA_USER_SETUP_CODE = r'''# Tech Connector Maya Bridge Startup Script v2
import base64
import os
import sys
import traceback

import maya.cmds as cmds

TECH_CONNECTOR_MAYA_BRIDGE_VERSION = "2"
TECH_CONNECTOR_MAYA_BRIDGE_BOOT_SOURCE = str(globals().get("__file__", ""))


def maya_execute_and_capture(encoded_payload):
    code = base64.b64decode(encoded_payload.encode("utf-8")).decode("utf-8")
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    class _TechConnectorCapture:
        def __init__(self):
            self.parts = []

        def write(self, value):
            self.parts.append(str(value))

        def flush(self):
            pass

    capture = _TechConnectorCapture()
    sys.stdout = capture
    sys.stderr = capture
    try:
        exec(code, globals(), globals())
    except Exception:
        traceback.print_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return "".join(capture.parts)


def _init_tech_connector_maya_bridge():
    preferred = int(os.environ.get("MAYA_COMMAND_PORT", "7001"))
    scan_count = max(1, int(os.environ.get("MAYA_COMMAND_PORT_SCAN_COUNT", "10")))
    opened_port = None
    for port in range(preferred, preferred + scan_count):
        port_name = ":%s" % port
        try:
            if cmds.commandPort(port_name, q=True):
                opened_port = port
                break
            cmds.commandPort(
                name=port_name,
                sourceType="python",
                echoOutput=True,
                noreturn=False,
            )
            opened_port = port
            break
        except Exception:
            continue
    if opened_port is None:
        cmds.warning("[Tech Connector] No free Maya commandPort was available.")
    else:
        print("[Tech Connector] Maya bridge v%s ready on port %s" % (
            TECH_CONNECTOR_MAYA_BRIDGE_VERSION,
            opened_port,
        ))

    try:
        if not cmds.pluginInfo("MayaLiveLinkPlugin", q=True, loaded=True):
            cmds.loadPlugin("MayaLiveLinkPlugin", quiet=True)
    except Exception:
        pass


cmds.evalDeferred(_init_tech_connector_maya_bridge)
'''


def managed_bootstrap_block() -> str:
    return f"{BLOCK_BEGIN}\n{MAYA_USER_SETUP_CODE.strip()}\n{BLOCK_END}\n"


def render_user_setup(existing: str) -> str:
    """Return a stable userSetup.py with exactly one current managed block."""

    source = str(existing or "")
    begin_count = source.count(BLOCK_BEGIN)
    end_count = source.count(BLOCK_END)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("Malformed Tech Connector managed block in userSetup.py")
    block = managed_bootstrap_block()
    if begin_count == 1:
        start = source.index(BLOCK_BEGIN)
        end = source.index(BLOCK_END, start) + len(BLOCK_END)
        prefix = source[:start].rstrip()
        suffix = source[end:].lstrip("\r\n")
        pieces = [value for value in (prefix, block.rstrip(), suffix.rstrip()) if value]
        return "\n\n".join(pieces).rstrip() + "\n"
    legacy = LEGACY_MAYA_USER_SETUP_CODE.strip()
    if legacy and legacy in source:
        source = source.replace(legacy, block.rstrip(), 1)
        return source.rstrip() + "\n"
    if not source.strip():
        return block
    return source.rstrip() + "\n\n" + block


def find_maya_script_dirs() -> list[Path]:
    """Return standard existing user script directories for installed Maya versions."""

    maya_root = Path.home() / "Documents" / "maya"
    if not maya_root.exists():
        maya_root = Path.home() / "maya"
    if not maya_root.exists():
        return []
    candidates = [maya_root / "scripts"]
    candidates.extend(subdir / "scripts" for subdir in maya_root.glob("20*") if subdir.is_dir())
    return sorted(dict.fromkeys(path.resolve() for path in candidates), key=str)


def _target_script_dirs(script_dirs: Iterable[str | Path] | None) -> list[Path]:
    if script_dirs is not None:
        return sorted(dict.fromkeys(Path(path).expanduser().resolve() for path in script_dirs), key=str)
    discovered = find_maya_script_dirs()
    return discovered or [(Path.home() / "Documents" / "maya" / "scripts").resolve()]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def verify_maya_livelink_installation(
    script_dirs: Iterable[str | Path] | None = None,
) -> dict[str, object]:
    """Read back exact managed bootstrap content without changing user files."""

    paths = [directory / "userSetup.py" for directory in _target_script_dirs(script_dirs)]
    expected = managed_bootstrap_block().strip()
    rows = []
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8") if path.is_file() else ""
            current = (
                content.count(BLOCK_BEGIN) == 1
                and content.count(BLOCK_END) == 1
                and expected in content
            )
            rows.append({
                "path": str(path),
                "exists": path.is_file(),
                "current": current,
                "managed_block_present": expected in content,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest() if content else "",
            })
        except Exception as exc:
            rows.append({"path": str(path), "exists": path.is_file(), "current": False, "error": str(exc)})
    return {
        "ok": bool(rows) and all(bool(row.get("current")) for row in rows),
        "bootstrap_version": BOOTSTRAP_VERSION,
        "paths": rows,
    }


def install_maya_livelink_plugin(
    script_dirs: Iterable[str | Path] | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    """Install or update the managed bootstrap atomically; unchanged files are not rewritten."""

    changed_paths = []
    unchanged_paths = []
    planned_paths = []
    errors = []
    for script_dir in _target_script_dirs(script_dirs):
        user_setup = script_dir / "userSetup.py"
        try:
            existing = user_setup.read_text(encoding="utf-8") if user_setup.is_file() else ""
            desired = render_user_setup(existing)
            if desired == existing:
                unchanged_paths.append(str(user_setup))
                continue
            planned_paths.append(str(user_setup))
            if not dry_run:
                _atomic_write(user_setup, desired)
                changed_paths.append(str(user_setup))
        except Exception as exc:
            errors.append({"path": str(user_setup), "error": str(exc)})
    verification = (
        {"ok": not errors, "bootstrap_version": BOOTSTRAP_VERSION, "paths": []}
        if dry_run
        else verify_maya_livelink_installation(script_dirs)
    )
    return {
        "ok": not errors and bool(verification.get("ok")),
        "dry_run": bool(dry_run),
        "bootstrap_version": BOOTSTRAP_VERSION,
        "changed_paths": changed_paths,
        "unchanged_paths": unchanged_paths,
        "planned_paths": planned_paths,
        "errors": errors,
        "verification": verification,
    }


__all__ = [
    "BLOCK_BEGIN",
    "BLOCK_END",
    "BOOTSTRAP_VERSION",
    "MAYA_USER_SETUP_CODE",
    "find_maya_script_dirs",
    "install_maya_livelink_plugin",
    "managed_bootstrap_block",
    "render_user_setup",
    "verify_maya_livelink_installation",
]
