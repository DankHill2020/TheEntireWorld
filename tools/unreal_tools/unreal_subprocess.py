import subprocess
import time
import os
import json
import requests


def run_get_skeletons(unreal_project_path, log_file_path,
                              unreal_command_path="C:/Program Files/Epic "
                                                  "Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"):
    """
    :param unreal_project_path: path to the unreal project
    :param log_file_path: log file path for returning output (function exists to find this in unreal_project_data.py)
    :param unreal_command_path: unreal cmd exe for version of editor (function exists to find this in unreal_project_data.py)
    :return:
    """
    try:
        payload = {
            "function": "unreal_tools.get_skeletons.get_all_assets_of_type",
            "args": ["Skeleton", "/Game/"]
            }

        response = requests.post("http://127.0.0.1:12347", json=payload)
        print(response.json())
        return response.json()
    except:
        script_dir = os.path.dirname(__file__)
        unreal_cmd = [
            unreal_command_path,
            unreal_project_path,
            "-run=pythonscript",
            "-script=" + script_dir + "/get_skeletons.py"
        ]

        try:
            result = subprocess.run(unreal_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            '''print("STDOUT:\n", result.stdout)
            print("STDERR:\n", result.stderr)'''

            time.sleep(5)

            with open(log_file_path, "r") as log_file:
                log_data = log_file.read()

                if "'class_name': 'Skeleton'" in log_data:
                    start_index = log_data.find("{")
                    end_index = log_data.rfind("}") + 1


                    relevant_data = log_data[start_index:end_index]
                    return relevant_data

                # If no relevant data found, return a fallback message
                return "No relevant asset dictionary found in the log."

        except subprocess.CalledProcessError as e:
            return f"Error: {e.stderr}"


def run_create_cinematic_sequence(anim_dict_path, destination_path, unreal_project_path, log_file_path,
                                  unreal_command_path="C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"):
    try:
        payload = {
            "function": "unreal_tools.sequence_importer.create_cinematic_sequence_from_json",
            "args": [anim_dict_path, destination_path],
            "kwargs": {
                "from_cmd": False
            }
        }

        response = requests.post("http://127.0.0.1:12347", json=payload)
        print(response.json())
        return response.json()
    except:
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
    try:
        payload = {
            "function": "unreal_tools.sequence_importer.import_gameplay_animations_from_json",
            "args": [anim_dict_path]
            }

        response = requests.post("http://127.0.0.1:12347", json=payload)
        print(response.json())
        return response.json()
    except:
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
