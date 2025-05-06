import os
import json
import winreg
import glob
import re


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

    project_dir = os.path.dirname(uproject_path)
    ini_path = os.path.join(project_dir, "Config", "DefaultEngine.ini")
    if not os.path.exists(ini_path):
        raise FileNotFoundError(f"DefaultEngine.ini not found at: {ini_path}")

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
    for i in range(section_start + 1, len(lines)):
        if lines[i].startswith('['):
            section_end = i
            break
        match = re.match(rf"{re.escape(startup_script_key)}\[(\d+)\]", lines[i])
        if match:
            existing_indices.append(int(match.group(1)))

    new_index = max(existing_indices, default=-1) + 1
    cleaned_path = re.sub(r"[\"']", "", script_path.replace(os.sep, '/'))
    new_line = f"{startup_script_key}[{new_index}]={cleaned_path}\n"
    lines.insert(section_end, new_line)
    with open(ini_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)





