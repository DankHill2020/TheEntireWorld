import os
import json
import os
import winreg
import glob
import re
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path


def get_engine_association(uproject_path):
    """
    Returns the Engine Version for the uproject
    :param uproject_path: actual uproject path
    :return: If found, returns the Engine Version for the unreal version
    """
    with open(uproject_path, "r") as f:
        uproject = json.load(f)
    return uproject.get("EngineAssociation", None)


def get_unreal_cmd_exe(uproject_path):
    """
    Returns the Engine cmd exe location for the uproject
    :param uproject_path: actual uproject path
    :return: If found, returns the cmd.exe for the unreal version
    """
    if not os.path.exists(uproject_path):
        return None

    # Read the uproject file to get EngineAssociation
    with open(uproject_path, 'r') as f:
        uproject_data = json.load(f)

    engine_association = uproject_data.get("EngineAssociation", None)

    if not engine_association:
        return None

    # Check registry for installed Unreal Engine versions
    ue_install_path = get_unreal_install_path(engine_association)

    if not ue_install_path:
        return None

    # Construct the path to UnrealEditor-Cmd.exe
    cmd_exe_path = os.path.join(ue_install_path, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")

    return cmd_exe_path if os.path.exists(cmd_exe_path) else None


def get_unreal_install_path(engine_version):
    """
    Check the Windows Registry for Unreal Engine install locations.

    :param engine_version: after finding engine version, it fills in the rest
    :return:
    """

    unreal_reg_path = r"SOFTWARE\Epic Games\Unreal Engine"

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, unreal_reg_path) as key:
            i = 0
            while True:
                try:
                    version = winreg.EnumKey(key, i)
                    if version == engine_version:
                        with winreg.OpenKey(key, version) as subkey:
                            install_path, _ = winreg.QueryValueEx(subkey, "InstalledDirectory")
                            return install_path
                except OSError:
                    break
                i += 1
    except FileNotFoundError:
        pass

    # Fallback: Check default install locations
    default_paths = [
        f"C:/Program Files/Epic Games/UE_{engine_version}",
        f"D:/Program Files/Epic Games/UE_{engine_version}"
    ]

    for path in default_paths:
        if os.path.exists(path):
            return path

    return None


def get_latest_unreal_log(uproject_path):
    """
    Finds the latest modified Unreal Engine log file for a given .uproject.
    :param uproject_path: actual uproject path
    :return:
    """

    proj_base_name = os.path.basename(uproject_path).split('.')[0]
    proj_dir = os.path.dirname(uproject_path)
    log_dir = os.path.join(proj_dir, "Saved", "Logs")

    if not os.path.exists(log_dir):
        return None

    # Find all logs that match the project's base name
    log_pattern = os.path.join(log_dir, f"{proj_base_name}*.log")
    log_files = glob.glob(log_pattern)

    if not log_files:
        return None

    # Get the most recently modified log file
    latest_log = max(log_files, key=os.path.getmtime)
    return latest_log


def ensure_unreal_python_plugin_enabled(uproject_path):
    """
    Enables PythonScriptPlugin in the .uproject if the project does not already
    declare it. Unreal needs this plugin for startup Python scripts.
    """
    if not os.path.isfile(uproject_path):
        raise FileNotFoundError(f"uproject not found: {uproject_path}")

    with open(uproject_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    plugins = data.setdefault("Plugins", [])
    if not isinstance(plugins, list):
        plugins = []
        data["Plugins"] = plugins

    for plugin in plugins:
        if str(plugin.get("Name", "")).lower() == "pythonscriptplugin":
            if plugin.get("Enabled") is not True:
                plugin["Enabled"] = True
                with open(uproject_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                    f.write("\n")
            return

    plugins.append({"Name": "PythonScriptPlugin", "Enabled": True})
    with open(uproject_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.write("\n")


def _tree_digest(root):
    digest = hashlib.sha256()
    root = Path(root)
    for path in sorted(value for value in root.rglob("*") if value.is_file()):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if any(part in {"Binaries", "Intermediate", "Saved"} for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _set_uproject_plugin_enabled(uproject_path, plugin_name, enabled=True):
    path = Path(uproject_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    plugins = data.setdefault("Plugins", [])
    if not isinstance(plugins, list):
        plugins = []
        data["Plugins"] = plugins
    entry = next(
        (
            item
            for item in plugins
            if str(item.get("Name") or "").lower() == str(plugin_name).lower()
        ),
        None,
    )
    changed = False
    if entry is None:
        plugins.append({"Name": str(plugin_name), "Enabled": bool(enabled)})
        changed = True
    elif bool(entry.get("Enabled")) != bool(enabled):
        entry["Enabled"] = bool(enabled)
        changed = True
    if changed:
        path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
    return changed


def _compiled_plugin_status(plugin_root):
    root = Path(plugin_root)
    binary_dir = root / "Binaries" / "Win64"
    binaries = [
        path
        for path in binary_dir.glob("*AIStudioBridge*")
        if path.is_file() and path.suffix.lower() in {".dll", ".modules"}
    ]
    build_inputs = []
    for relative in ("Source",):
        source_root = root / relative
        if source_root.is_dir():
            build_inputs.extend(
                path
                for path in source_root.rglob("*")
                if path.is_file() and path.suffix.lower() in {".h", ".hpp", ".cpp", ".cs"}
            )
    descriptor = root / "AIStudioBridge.uplugin"
    if descriptor.is_file():
        build_inputs.append(descriptor)
    newest_binary = max((path.stat().st_mtime_ns for path in binaries), default=0)
    newest_input = max((path.stat().st_mtime_ns for path in build_inputs), default=0)
    return {
        "compiled_binaries": [str(path) for path in binaries],
        "binary_present": bool(binaries),
        "binary_current": bool(binaries and newest_binary >= newest_input),
        "newest_binary_mtime_ns": newest_binary,
        "newest_build_input_mtime_ns": newest_input,
    }


def install_ai_studio_bridge_plugin(uproject_path, source_plugin_root=None):
    """Install source and enable the plugin only when its editor binary is current."""
    project_file = Path(uproject_path).expanduser().resolve()
    if not project_file.is_file():
        raise FileNotFoundError(f"uproject not found: {project_file}")
    tools_root = Path(__file__).resolve().parent.parent
    source = Path(source_plugin_root or tools_root / "plugins" / "AIStudioBridge").resolve()
    descriptor = source / "AIStudioBridge.uplugin"
    if not descriptor.is_file():
        raise FileNotFoundError(f"AIStudioBridge descriptor not found: {descriptor}")

    target = project_file.parent / "Plugins" / "AIStudioBridge"
    source_digest = _tree_digest(source)
    target_digest_before = _tree_digest(target) if target.is_dir() else ""
    copied = source_digest != target_digest_before
    if copied:
        target.mkdir(parents=True, exist_ok=True)
        for name in (
            "AIStudioBridge.uplugin",
            "AIStudioBridgeCapabilities.json",
            "README.md",
        ):
            source_file = source / name
            if source_file.is_file():
                shutil.copy2(source_file, target / name)
        for name in ("Config", "Source"):
            source_dir = source / name
            if source_dir.is_dir():
                shutil.copytree(source_dir, target / name, dirs_exist_ok=True)

    binary_status = _compiled_plugin_status(target)
    build_required = not binary_status["binary_current"]
    descriptor_changed = _set_uproject_plugin_enabled(
        project_file,
        "AIStudioBridge",
        not build_required,
    )
    ensure_unreal_python_plugin_enabled(str(project_file))
    progress_phases = [
        {
            "id": "select_project",
            "label": "Select Unreal project",
            "status": "completed",
            "percent": 10,
            "message": str(project_file),
        },
        {
            "id": "install_plugin_source",
            "label": "Install plugin source",
            "status": "completed",
            "percent": 30,
            "message": "Plugin source copied." if copied else "Plugin source already current.",
        },
        {
            "id": "build_plugin",
            "label": "Build plugin",
            "status": "pending" if build_required else "completed",
            "percent": 55,
            "message": (
                "A current Unreal Editor binary must be built before enablement."
                if build_required
                else "Current compiled editor binary verified."
            ),
        },
        {
            "id": "enable_plugin",
            "label": "Enable plugin",
            "status": "blocked" if build_required else "completed",
            "percent": 70,
            "message": (
                "Waiting for a successful build."
                if build_required
                else "AIStudioBridge is enabled in the project descriptor."
            ),
        },
        {
            "id": "restart_editor",
            "label": "Restart Unreal",
            "status": "pending" if copied or descriptor_changed else "not_required",
            "percent": 85,
            "message": "Restart Unreal to load the updated module." if copied or descriptor_changed else "No restart required.",
        },
        {
            "id": "validate_bridge",
            "label": "Validate Python bridge",
            "status": "pending",
            "percent": 100,
            "message": "Waiting for reflected method and HTTP bridge readback.",
        },
    ]
    return {
        "ok": True,
        "project": str(project_file),
        "source_plugin": str(source),
        "installed_plugin": str(target),
        "copied": copied,
        "enabled": not build_required,
        "uproject_changed": descriptor_changed,
        "source_digest": source_digest,
        **binary_status,
        "build_required": build_required,
        "restart_required": copied or descriptor_changed,
        "progress_phases": progress_phases,
    }


def build_ai_studio_bridge_plugin(
    uproject_path,
    source_plugin_root=None,
    progress_callback=None,
):
    """Build, install, and enable AIStudioBridge while streaming progress."""
    project_file = Path(uproject_path).expanduser().resolve()
    if not project_file.is_file():
        raise FileNotFoundError(f"uproject not found: {project_file}")
    tools_root = Path(__file__).resolve().parent.parent
    source = Path(source_plugin_root or tools_root / "plugins" / "AIStudioBridge").resolve()
    engine_association = get_engine_association(str(project_file))
    engine_root = Path(get_unreal_install_path(engine_association) or "")
    run_uat = engine_root / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
    if not run_uat.is_file():
        raise FileNotFoundError(
            f"RunUAT.bat not found for EngineAssociation {engine_association!r}: {run_uat}"
        )
    callback = progress_callback if callable(progress_callback) else lambda _event: None
    package_root = Path(tempfile.mkdtemp(prefix="AIStudioBridge_Build_"))
    command = [
        str(run_uat),
        "BuildPlugin",
        f"-Plugin={source / 'AIStudioBridge.uplugin'}",
        f"-Package={package_root}",
        "-TargetPlatforms=Win64",
        "-Rocket",
    ]
    callback(
        {
            "id": "build_plugin",
            "label": "Build plugin",
            "status": "in_progress",
            "percent": 45,
            "message": "Starting Unreal AutomationTool.",
        }
    )
    output_lines = []
    try:
        process = subprocess.Popen(
            command,
            cwd=str(source),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        assert process.stdout is not None
        for line in process.stdout:
            stripped = line.rstrip()
            output_lines.append(stripped)
            lower = stripped.lower()
            if "compile" in lower:
                percent = 52
            elif "link" in lower:
                percent = 58
            elif "building plugin for target platforms" in lower:
                percent = 62
            else:
                percent = 48
            callback(
                {
                    "id": "build_plugin",
                    "label": "Build plugin",
                    "status": "in_progress",
                    "percent": percent,
                    "message": stripped,
                }
            )
        return_code = process.wait()
        if return_code != 0:
            return {
                "ok": False,
                "status": "build_failed",
                "return_code": return_code,
                "command": command,
                "output_tail": output_lines[-100:],
            }

        target = project_file.parent / "Plugins" / "AIStudioBridge"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("Binaries", "Source"):
            source_dir = package_root / name
            if source_dir.is_dir():
                shutil.copytree(source_dir, target / name, dirs_exist_ok=True)
        for name in (
            "AIStudioBridge.uplugin",
            "AIStudioBridgeCapabilities.json",
            "README.md",
        ):
            source_file = source / name
            if source_file.is_file():
                shutil.copy2(source_file, target / name)
        binary_status = _compiled_plugin_status(target)
        if not binary_status["binary_current"]:
            return {
                "ok": False,
                "status": "built_binary_not_current",
                **binary_status,
                "output_tail": output_lines[-100:],
            }
        changed = _set_uproject_plugin_enabled(project_file, "AIStudioBridge", True)
        ensure_unreal_python_plugin_enabled(str(project_file))
        callback(
            {
                "id": "enable_plugin",
                "label": "Enable plugin",
                "status": "completed",
                "percent": 75,
                "message": "Current binary installed; AIStudioBridge enabled.",
            }
        )
        return {
            "ok": True,
            "status": "built_installed_and_enabled",
            "project": str(project_file),
            "installed_plugin": str(target),
            "uproject_changed": changed,
            "restart_required": True,
            "command": command,
            **binary_status,
            "output_tail": output_lines[-100:],
        }
    finally:
        shutil.rmtree(package_root, ignore_errors=True)


def add_unreal_startup_script(uproject_path, script_path):
    """
    Adds a startup script to DefaultEngine.ini for a given Unreal project.
    Appends to StartupScripts[N]=... under [PythonScriptPlugin.PythonScriptPluginSettings].

    :param uproject_path: actual uproject path
    :param script_path: Full path to the Python script to add
    """
    if not os.path.isfile(uproject_path):
        raise FileNotFoundError(f"uproject not found: {uproject_path}")
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"Script not found: {script_path}")

    ensure_unreal_python_plugin_enabled(uproject_path)
    project_dir = os.path.dirname(uproject_path)
    config_dir = os.path.join(project_dir, "Config")
    os.makedirs(config_dir, exist_ok=True)
    ini_path = os.path.join(project_dir, "Config", "DefaultEngine.ini")
    if not os.path.exists(ini_path):
        with open(ini_path, "w", encoding="utf-8") as f:
            f.write("")

    with open(ini_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    section_header = "[/Script/PythonScriptPlugin.PythonScriptPluginSettings]"
    startup_script_key = "StartupScripts"
    existing_indices = []

    section_start = None
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            section_start = i
            break

    if section_start is None:
        lines.append(f"\n{section_header}\n")
        section_start = len(lines) - 1

    section_end = len(lines)
    cleaned_path = re.sub(r"[\"']", "", script_path.replace(os.sep, '/'))
    for i in range(section_start + 1, len(lines)):
        if lines[i].startswith('['):
            section_end = i
            break
        match = re.match(rf"{re.escape(startup_script_key)}\[(\d+)\]", lines[i])
        if match:
            existing_indices.append(int(match.group(1)))

        if cleaned_path in lines[i]:
            return

    new_index = max(existing_indices, default=-1) + 1
    new_line = f"{startup_script_key}[{new_index}]={cleaned_path}\n"

    lines.insert(section_end, new_line)
    with open(ini_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)





