import unreal
import sys
import os
import json


def import_animations_from_json(anim_dict_path):
    """
    Function to call via the subprocess version / unreal cmd.exe version of the gameplay import to import all anims in json
    :param anim_dict_path: path to json with sequence_data
    :return:
    """
    if not os.path.exists(anim_dict_path):
        unreal.log_error(f"FILE DOES NOT EXIST: {anim_dict_path}")
        return

    script_dir = os.path.dirname(__file__)
    tools_dir = os.path.dirname(script_dir)
    sys.path.append(tools_dir)

    from unreal_tools import sequence_importer
    sequence_path = sequence_importer.import_gameplay_animations_from_json(anim_dict_path)
    unreal.log(f"Imported Animations for : {sequence_path}")
    return sequence_path


if __name__ == "__main__":
    # Load the args
    script_dir = os.path.dirname(__file__)
    args_path = "C:/temp/gameplay_animation_args.json"

    if not os.path.exists(args_path):
        raise ValueError("Missing sequence_args.json")

    with open(args_path, "r") as f:
        args = json.load(f)

    anim_dict_path = args.get("anim_dict_path")

    if not anim_dict_path:
        raise ValueError("Missing required argument: anim_dict_path")

    unreal.log(f"Parsed anim_dict_path: {anim_dict_path}")

    import_animations_from_json(anim_dict_path)

