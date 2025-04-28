import sys
import subprocess
import maya.cmds as cmds
import os
import winreg

def update_maya_script_path(new_path):
    """
    Update the MAYA_SCRIPT_PATH environment variable for the current Windows user.
    If it already exists, append the new_path if not already present.
    If it doesn't exist, create it.

    :param new_path: Path to add to MAYA_SCRIPT_PATH
    """
    try:
        new_path = os.path.normpath(new_path)

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Environment",
                            0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as env_key:
            try:
                existing_value, value_type = winreg.QueryValueEx(env_key, "MAYA_SCRIPT_PATH")
                paths = existing_value.split(";")
                if new_path not in paths:
                    updated_value = existing_value + ";" + new_path
                    winreg.SetValueEx(env_key, "MAYA_SCRIPT_PATH", 0, value_type, updated_value)

            except FileNotFoundError:
                winreg.SetValueEx(env_key, "MAYA_SCRIPT_PATH", 0, winreg.REG_EXPAND_SZ, new_path)

    except Exception as e:
        print(f"Failed to update MAYA_SCRIPT_PATH: {e}")

tools_dir = os.path.dirname(__file__)
if tools_dir not in sys.path:
    sys.path.append(tools_dir)
tools_dir = tools_dir.replace("\\", "/") + "/"

try:
    import requests
except:
    maya_version = cmds.about(version=True)

    mayapy_path = os.path.join("C:\\Program Files", "Autodesk", f"Maya{maya_version}", "bin", "mayapy.exe")
    subprocess.check_call([mayapy_path, "-m", "ensurepip", "--upgrade"])
    subprocess.check_call([mayapy_path, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([mayapy_path, "-m", "pip", "install", "requests"])

update_maya_script_path(tools_dir)