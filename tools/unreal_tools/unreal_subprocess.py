import subprocess
import time
import os
import json
import requests


def _post_unreal(payload):
    from tech_connector.bridges.session_authorization import bridge_session_token
    payload = dict(payload, bridge_session=bridge_session_token("unreal"))
    port = int(os.environ.get("UNREAL_HTTP_PORT", "12347"))
    response = requests.post("http://127.0.0.1:{}".format(port), json=payload, timeout=125)
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError("Unreal bridge: {} ({})".format(
            data["error"], data.get("code", response.status_code)))
    response.raise_for_status()
    return data


def _validate_asset_result(data, asset_type):
    if not isinstance(data, dict) or any(
        not isinstance(path, str) or not path.startswith("/")
        or not isinstance(row, dict) or row.get("class_name") != asset_type
        for path, row in data.items()
    ):
        raise RuntimeError("Unreal returned an invalid {} asset response.".format(asset_type))
    return data


def run_get_skeletons(unreal_project_path, log_file_path,
                              unreal_command_path="C:/Program Files/Epic "
                                                  "Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe",
                      asset_type="Skeleton"):
    """
    :param asset_type: type of asset to search for
    :param unreal_project_path: path to the unreal project
    :param log_file_path: log file path for returning output (function exists to find this in unreal_project_data.py)
    :param unreal_command_path: unreal cmd exe for version of editor (function exists to find this in unreal_project_data.py)
    :return:
    """
    try:
        payload = {
            "function": "unreal_tools.get_skeletons.get_all_assets_of_type",
            "args": [asset_type, "/Game/"]
            }

        return _validate_asset_result(_post_unreal(payload), asset_type)
    except requests.ConnectionError:
        if not unreal_command_path or not os.path.isfile(unreal_command_path):
            raise RuntimeError("Unreal bridge is unavailable and the Unreal command-line editor was not found.")
        script_dir = os.path.dirname(__file__)
        unreal_cmd = [
            unreal_command_path,
            unreal_project_path,
            "-run=pythonscript",
            '-script="{}" {}'.format(script_dir + "/get_skeletons.py", asset_type)
        ]

        try:
            result = subprocess.run(unreal_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            for line in (result.stdout + "\n" + result.stderr).splitlines():
                if "HIK_ASSETS_JSON=" in line:
                    return _validate_asset_result(
                        json.loads(line.split("HIK_ASSETS_JSON=", 1)[1]), asset_type)
            raise RuntimeError("Unreal asset scan completed without an asset result.")

        except subprocess.CalledProcessError as e:
            return f"Error: {e.stderr}"


def run_create_cinematic_sequence(anim_dict_path, destination_path, unreal_project_path, log_file_path,
                                  unreal_command_path="C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"):
    """

    :param anim_dict_path: Path of Json data
    :param destination_path: Path to save Cinematic
    :param unreal_project_path: path to the unreal project
    :param log_file_path: log file path for returning output (function exists to find this in unreal_project_data.py)
    :param unreal_command_path: unreal cmd exe for version of editor (function exists to find this in unreal_project_data.py)
    :return:
    """
    try:
        payload = {
            "function": "unreal_tools.sequence_importer.create_cinematic_sequence_from_json",
            "args": [anim_dict_path, destination_path],
            "kwargs": {
                "from_cmd": False
            }
        }

        return _post_unreal(payload)
    except requests.ConnectionError:
        script_dir = os.path.dirname(__file__)
        script_path = os.path.join(script_dir, "sequence_func.py").replace('\\', '/')

        # Write arguments to a temp file
        temp_args_file = "C:/temp/sequence_args.json"

        os.makedirs(os.path.dirname(temp_args_file), exist_ok=True)

        with open(temp_args_file, "w") as f:
            json.dump({
                "anim_dict_path": anim_dict_path,
                "destination_path": destination_path
            }, f)

        unreal_cmd = [
            unreal_command_path,
            unreal_project_path,
            "-run=pythonscript",
            "-script=" + script_path
        ]

        try:
            result = subprocess.run(unreal_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            '''print("STDOUT:\n", result.stdout)
            print("STDERR:\n", result.stderr)'''

            time.sleep(5)

            if os.path.exists(log_file_path):
                with open(log_file_path, "r") as log_file:
                    log_data = log_file.read()
                    print("Log Output:\n", log_data)
                    return log_data

            return "Log file not found."

        except subprocess.CalledProcessError as e:
            return f"Error: {e.stderr}"


def run_import_gameplay_animations(anim_dict_path, unreal_project_path, log_file_path,
                                  unreal_command_path="C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"):
    """

    :param anim_dict_path: Path of Json data
    :param unreal_project_path: path to the unreal project
    :param log_file_path: log file path for returning output (function exists to find this in unreal_project_data.py)
    :param unreal_command_path: unreal cmd exe for version of editor (function exists to find this in unreal_project_data.py)
    :return:
    """
    try:
        payload = {
            "function": "unreal_tools.sequence_importer.import_gameplay_animations_from_json",
            "args": [anim_dict_path]
            }

        return _post_unreal(payload)
    except requests.ConnectionError:
        script_dir = os.path.dirname(__file__)
        script_path = os.path.join(script_dir, "gameplay_import_func.py").replace('\\', '/')

        # Write arguments to a temp file
        temp_args_file = "C:/temp/gameplay_animation_args.json"

        os.makedirs(os.path.dirname(temp_args_file), exist_ok=True)

        with open(temp_args_file, "w") as f:
            json.dump({
                "anim_dict_path": anim_dict_path,
            }, f)

        unreal_cmd = [
            unreal_command_path,
            unreal_project_path,
            "-run=pythonscript",
            "-script=" + script_path
        ]

        try:
            result = subprocess.run(unreal_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            '''print("STDOUT:\n", result.stdout)
            print("STDERR:\n", result.stderr)'''

            time.sleep(5)

            if os.path.exists(log_file_path):
                with open(log_file_path, "r") as log_file:
                    log_data = log_file.read()
                    print("Log Output:\n", log_data)
                    return log_data

            return "Log file not found."

        except subprocess.CalledProcessError as e:
            return f"Error: {e.stderr}"


def run_create_modular_control_rig(skeletal_mesh_name, rig_name, joint_map, unreal_project_path, log_file_path,
                                  unreal_command_path="C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"):
    """

    :param joint_map: Joint Map from HumanIK UI, for clear mapping for biped body parts
    :param rig_name: control rig asset name (saved to same folder as skeletal mesh)
    :param skeletal_mesh_name: skeletal mesh to assign to rig
    :param unreal_project_path: path to the unreal project
    :param log_file_path: log file path for returning output (function exists to find this in unreal_project_data.py)
    :param unreal_command_path: unreal cmd exe for version of editor (function exists to find this in unreal_project_data.py)
    :return:
    """
    try:
        payload = {
            "function": "unreal_tools.control_rig.build_modular_fk_control_rig",
            "args": [skeletal_mesh_name, rig_name, joint_map]
            }

        return _post_unreal(payload)
    except requests.ConnectionError:
        script_dir = os.path.dirname(__file__)
        script_path = os.path.join(script_dir, "gameplay_import_func.py").replace('\\', '/')

        # Write arguments to a temp file
        temp_args_file = "C:/temp/modular_rig_args.json"

        os.makedirs(os.path.dirname(temp_args_file), exist_ok=True)

        with open(temp_args_file, "w") as f:
            json.dump({
                "skeletal_mesh_name": skeletal_mesh_name,
                "rig_name": rig_name,
                "joint_map": joint_map,
            }, f)

        unreal_cmd = [
            unreal_command_path,
            unreal_project_path,
            "-run=pythonscript",
            "-script=" + script_path
        ]

        try:
            result = subprocess.run(unreal_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            '''print("STDOUT:\n", result.stdout)
            print("STDERR:\n", result.stderr)'''

            time.sleep(5)

            if os.path.exists(log_file_path):
                with open(log_file_path, "r") as log_file:
                    log_data = log_file.read()
                    print("Log Output:\n", log_data)
                    return log_data

            return "Log file not found."

        except subprocess.CalledProcessError as e:
            raise RuntimeError("Unreal asset scan failed: {}".format(e.stderr)) from e
