import subprocess
import time
import os
import json
import tempfile
import requests


def _post_unreal(payload):
    from tech_connector.bridges.session_authorization import bridge_session_token
    payload = dict(payload, bridge_session=bridge_session_token("unreal"))
    port = int(os.environ.get("UNREAL_HTTP_PORT", "12347"))
    response = requests.post("http://127.0.0.1:{}".format(port), json=payload, timeout=125)
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Unreal bridge returned a non-JSON response (HTTP {}).".format(response.status_code)
        ) from exc
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError("Unreal bridge: {} ({})".format(
            data["error"], data.get("code", response.status_code)))
    response.raise_for_status()
    return data


def _run_sequence_command(script_name, payload, unreal_project_path, unreal_command_path, timeout=900):
    """Run one isolated Unreal command job and read its structured result file."""
    if not unreal_command_path or not os.path.isfile(unreal_command_path):
        raise RuntimeError("Unreal bridge is unavailable and UnrealEditor-Cmd was not found.")
    if not unreal_project_path or not os.path.isfile(unreal_project_path):
        raise RuntimeError("Unreal bridge is unavailable and the .uproject path is invalid.")
    script_path = os.path.join(os.path.dirname(__file__), script_name).replace("\\", "/")
    with tempfile.TemporaryDirectory(prefix="tc_sequence_import_") as job_dir:
        args_path = os.path.join(job_dir, "args.json")
        result_path = os.path.join(job_dir, "result.json")
        with open(args_path, "w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream)
        environment = os.environ.copy()
        environment["TC_SEQUENCE_ARGS_PATH"] = args_path
        environment["TC_SEQUENCE_RESULT_PATH"] = result_path
        command = [
            unreal_command_path, unreal_project_path, "-run=pythonscript", "-script=" + script_path,
        ]
        try:
            completed = subprocess.run(
                command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=int(timeout), env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Unreal sequence import timed out after {timeout} seconds.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "Unreal command failed.").strip()
            raise RuntimeError(detail[-4000:]) from exc
        if not os.path.isfile(result_path):
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                "Unreal command completed without a structured result. " + detail[-2000:]
            )
        with open(result_path, "r", encoding="utf-8") as stream:
            result = json.load(stream)
        if not isinstance(result, dict):
            raise RuntimeError("Unreal command returned an invalid sequence result.")
        return result


def _validate_asset_result(data, asset_type):
    if not isinstance(data, dict) or any(
        not isinstance(path, str) or not path.startswith("/")
        or not isinstance(row, dict) or row.get("class_name") != asset_type
        for path, row in data.items()
    ):
        raise RuntimeError("Unreal returned an invalid {} asset response.".format(asset_type))
    return data


def run_list_skeletal_import_targets(directory="/Game"):
    """List Skeletal Mesh, Skeleton, and PhysicsAsset choices in the live Unreal Editor."""
    return _post_unreal({
        "function": "unreal_tools.skeletal_mesh_import.list_skeletal_import_targets",
        "args": [str(directory or "/Game")],
    })


def run_import_skeletal_mesh_fbx(
    source_file,
    rig_name,
    destination_path="/Game/Characters",
    existing_skeletal_mesh_path="",
    skeleton_mode="create_new",
    existing_skeleton_path="",
    create_physics_asset=True,
):
    """Import/update a skeletal FBX through the authenticated live Unreal bridge."""
    return _post_unreal({
        "function": "unreal_tools.skeletal_mesh_import.import_skeletal_mesh_fbx",
        "args": [source_file, rig_name, destination_path],
        "kwargs": {
            "existing_skeletal_mesh_path": existing_skeletal_mesh_path,
            "skeleton_mode": skeleton_mode,
            "existing_skeleton_path": existing_skeleton_path,
            "create_physics_asset": bool(create_physics_asset),
        },
    })


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
        return _run_sequence_command(
            "sequence_func.py",
            {"anim_dict_path": anim_dict_path, "destination_path": destination_path},
            unreal_project_path, unreal_command_path,
        )


def run_retry_failed_cinematic_sequence(
    anim_dict_path, previous_result, destination_path, unreal_project_path, log_file_path,
    unreal_command_path="C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe",
):
    """Retry only entry IDs identified as failed by a previous cinematic job."""
    payload = {
        "function": "unreal_tools.sequence_importer.retry_failed_cinematic_sequence_from_json",
        "args": [anim_dict_path, dict(previous_result or {}), destination_path],
        "kwargs": {"from_cmd": False},
    }
    try:
        return _post_unreal(payload)
    except requests.ConnectionError:
        return _run_sequence_command(
            "sequence_func.py",
            {
                "anim_dict_path": anim_dict_path, "destination_path": destination_path,
                "previous_result": dict(previous_result or {}),
            },
            unreal_project_path, unreal_command_path,
        )


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
        return _run_sequence_command(
            "gameplay_import_func.py", {"anim_dict_path": anim_dict_path},
            unreal_project_path, unreal_command_path,
        )


def run_preflight_sequence_import(
    anim_dict_path, unreal_project_path="", log_file_path="",
    unreal_command_path="C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe",
    mode="gameplay", destination_path="/Game/Animations",
):
    """Run the same Unreal resolution checks as import without modifying assets."""
    payload = {
        "function": "unreal_tools.sequence_importer.preflight_sequence_import_from_json",
        "args": [anim_dict_path],
        "kwargs": {"mode": mode, "destination_path": destination_path},
    }
    try:
        return _post_unreal(payload)
    except requests.ConnectionError:
        return _run_sequence_command(
            "sequence_preflight_func.py",
            {
                "anim_dict_path": anim_dict_path, "mode": mode,
                "destination_path": destination_path,
            },
            unreal_project_path, unreal_command_path,
        )


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
