import unreal
import sys
import os
import json


def create_cinematic_sequence_from_json(anim_dict_path, destination_path="/Game/Cinematics"):
    """

    :param anim_dict_path: path to json with sequence_data
    :param destination_path: path to where Cinematics are stored in project
    :return:
    """
    if not os.path.exists(anim_dict_path):
        unreal.log_error(f"FILE DOES NOT EXIST: {anim_dict_path}")
        return

    script_dir = os.path.dirname(__file__)
    tools_dir = os.path.dirname(script_dir)
    sys.path.append(tools_dir)

    from unreal_tools import sequence_importer
    sequence_path = sequence_importer.create_cinematic_sequence_from_json(anim_dict_path, destination_path=destination_path)
    unreal.log(f"Created Sequence at: {sequence_path}")
    return sequence_path


if __name__ == "__main__":
    script_dir = os.path.dirname(__file__)
    args_path = "C:/temp/sequence_args.json"

    if not os.path.exists(args_path):
        raise ValueError("Missing sequence_args.json")

    with open(args_path, "r") as f:
        args = json.load(f)

    anim_dict_path = args.get("anim_dict_path")
    destination_path = args.get("destination_path")

    if not anim_dict_path:
        raise ValueError("Missing required argument: anim_dict_path")

    unreal.log(f"Parsed anim_dict_path: {anim_dict_path}")
    unreal.log(f"Parsed destination_path: {destination_path}")

    create_cinematic_sequence_from_json(anim_dict_path, destination_path)

