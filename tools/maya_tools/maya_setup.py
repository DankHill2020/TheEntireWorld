import os
from pathlib import Path
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
    """Create or refresh the current profile's authenticated Maya startup."""
    from tech_connector.bridges.maya.maya_livelink_plugin import (
        find_maya_script_dirs,
        install_maya_livelink_plugin,
    )

    script_dirs = []
    try:
        script_dirs.append(Path(cmds.internalVar(userAppDir=True)) / "scripts")
    except Exception:
        pass
    script_dirs.extend(find_maya_script_dirs())
    script_dirs = list(dict.fromkeys(path.resolve() for path in script_dirs))
    if not script_dirs:
        print("No Maya user scripts directory found. Skipping userSetup.py.")
        return None

    # Prefer this running Maya profile. The managed installer creates the file
    # if needed, adds the checkout to sys.path before importing maya_tools, and
    # preserves unrelated studio/user startup code.
    script_dir = script_dirs[0]
    result = install_maya_livelink_plugin([script_dir])
    if not result.get("ok"):
        print("Failed to install Maya userSetup.py: {}".format(result.get("errors")))
        return None
    return str(script_dir / "userSetup.py")


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
    """Refresh the one managed, authenticated bridge block in userSetup.py."""
    return find_or_create_user_setup()


def install_current_maya_tools():
    """Install the current checkout into Maya; never runs merely on import."""
    tools_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if tools_dir not in sys.path:
        sys.path.append(tools_dir)

    try:
        import requests  # noqa: F401
    except Exception:
        try:
            maya_version = cmds.about(version=True)
            mayapy_path = os.path.join(
                "C:\\Program Files", "Autodesk", "Maya{}".format(maya_version),
                "bin", "mayapy.exe",
            )
            if os.path.exists(mayapy_path):
                subprocess.check_call([mayapy_path, "-m", "ensurepip", "--upgrade"])
                subprocess.check_call([mayapy_path, "-m", "pip", "install", "--upgrade", "pip"])
                subprocess.check_call([mayapy_path, "-m", "pip", "install", "requests"])
        except Exception as exc:
            print("Maya requests setup note: {}".format(exc))

    update_maya_script_path(tools_dir)
    add_tools_to_user_setup(tools_dir)
    setup_maya_livelink()
    try:
        from maya_tools import maya_menu

        maya_menu.create_menu_once()
    except Exception:
        pass
    return tools_dir


if __name__ == "__main__":
    install_current_maya_tools()
