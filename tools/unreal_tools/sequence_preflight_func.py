"""UnrealEditor-Cmd entry point for Sequence import dry runs."""

import json
import os
import sys

import unreal


def main():
    args_path = os.environ.get("TC_SEQUENCE_ARGS_PATH", "")
    result_path = os.environ.get("TC_SEQUENCE_RESULT_PATH", "")
    if not args_path or not os.path.isfile(args_path):
        raise ValueError("Missing TC_SEQUENCE_ARGS_PATH")
    with open(args_path, "r", encoding="utf-8") as stream:
        args = json.load(stream)
    tools_dir = os.path.dirname(os.path.dirname(__file__))
    if tools_dir not in sys.path:
        sys.path.append(tools_dir)
    from unreal_tools.sequence_importer import preflight_sequence_import_from_json

    result = preflight_sequence_import_from_json(
        args.get("anim_dict_path"), mode=args.get("mode", "gameplay"),
        destination_path=args.get("destination_path", "/Game/Animations"),
    )
    unreal.log("Sequence preflight: {}".format(result))
    if result_path:
        with open(result_path, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, default=str)
    return result


if __name__ == "__main__":
    main()
