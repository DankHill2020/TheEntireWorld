import os
import subprocess
import sys
import winreg

import maya.cmds as cmds


def update_maya_script_path(new_path):
    """Update MAYA_SCRIPT_PATH environment variable for the current Windows user."""
    try:
        new_path = os.path.normpath(new_path)
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        ) as env_key:
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


def find_or_create_user_setup():
    """Find an existing userSetup.py or create one without overwriting."""
    maya_script_path = os.environ.get("MAYA_SCRIPT_PATH", "")
    search_paths = maya_script_path.split(os.pathsep)

    for path in search_paths:
        user_setup_path = os.path.join(path, "userSetup.py")
        if os.path.isfile(user_setup_path):
            return user_setup_path

    for path in search_paths:
        if os.path.isdir(path) and os.access(path, os.W_OK):
            user_setup_path = os.path.join(path, "userSetup.py")
            if not os.path.exists(user_setup_path):
                try:
                    with open(user_setup_path, "w") as f:
                        f.write("# Auto-generated userSetup.py\n\n")
                    print(f"Created new userSetup.py at: {user_setup_path}")
                except Exception as e:
                    print(f"Failed to create userSetup.py at {path}: {e}")
            return user_setup_path

    return None


def add_tools_to_user_setup(tools_dir):
    """Add sys.path.append for tools_dir into userSetup.py if not present."""
    tools_dir = tools_dir.replace("\\", "/")
    user_setup_path = find_or_create_user_setup()
    if not user_setup_path:
        print("No userSetup.py found. Skipping.")
        return

    import_line = "import sys\n"
    sys_path_line = f"sys.path.append('{tools_dir}')\n"
    call_menu_line = "from maya_tools import maya_menu; maya_menu.create_menu_once()"

    try:
        with open(user_setup_path, "r", encoding="utf-8") as f:
            contents = f.read()

        with open(user_setup_path, "a", encoding="utf-8") as f:
            if import_line not in contents:
                f.write(import_line + "\n")
            if sys_path_line not in contents:
                f.write(sys_path_line + "\n")
            if call_menu_line not in contents:
                f.write(call_menu_line + "\n")
        print(f"Added tools path to {user_setup_path}")
    except Exception as e:
        print(f"Failed adding tools to userSetup.py: {e}")


def setup_maya_livelink():
    """Setup the entitlement-aware Maya bridge and official Live Link plugin."""
    livelink_code = (
        "# TECH_CONNECTOR_SECURE_MAYA_PORT\n"
        "try:\n"
        "    from maya_tools import maya_menu\n"
        "    maya_menu.initialize_command_port()\n"
        "except Exception:\n"
        "    pass\n"
        "try:\n"
        "    if not cmds.pluginInfo('MayaLiveLinkPlugin', q=True, loaded=True):\n"
        "        cmds.loadPlugin('MayaLiveLinkPlugin', quiet=True)\n"
        "except Exception:\n"
        "    pass\n"
    )
    user_setup_path = find_or_create_user_setup()
    if not user_setup_path:
        return
    try:
        with open(user_setup_path, "r", encoding="utf-8") as f:
            contents = f.read()
        if "TECH_CONNECTOR_SECURE_MAYA_PORT" not in contents:
            with open(user_setup_path, "a", encoding="utf-8") as f:
                f.write("\n# Entitlement-aware Live Link & Plugin Initialization\n" + livelink_code)
            print(f"Added entitlement-aware Live Link setup to {user_setup_path}")
    except Exception as e:
        print(f"Failed to append Live Link setup: {e}")


tools_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if tools_dir not in sys.path:
    sys.path.append(tools_dir)

try:
    import requests
except Exception:
    try:
        maya_version = cmds.about(version=True)
        mayapy_path = os.path.join("C:\\Program Files", "Autodesk", f"Maya{maya_version}", "bin", "mayapy.exe")
        if os.path.exists(mayapy_path):
            subprocess.check_call([mayapy_path, "-m", "ensurepip", "--upgrade"])
            subprocess.check_call([mayapy_path, "-m", "pip", "install", "--upgrade", "pip"])
            subprocess.check_call([mayapy_path, "-m", "pip", "install", "requests"])
    except Exception as exc:
        print(f"Maya requests setup note: {exc}")

update_maya_script_path(tools_dir)
add_tools_to_user_setup(tools_dir)
setup_maya_livelink()
try:
    from maya_tools import maya_menu

    maya_menu.create_menu_once()
except Exception:
    pass
