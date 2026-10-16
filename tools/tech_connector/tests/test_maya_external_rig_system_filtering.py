from __future__ import annotations

import ast
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[2]
CREATE_RIG = TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig.py"


def _ownership_helpers():
    tree = ast.parse(CREATE_RIG.read_text(encoding="utf-8"))
    names = {
        "_short_scene_name",
        "_extension_base_name",
        "_is_builder_owned_extension_root",
    }
    body = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef) and node.name in names
        ) or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_BUILDER_CONTROL_ROOT_SUFFIXES"
                for target in node.targets
            )
        )
    ]
    namespace = {}
    exec(
        compile(
            ast.Module(body=body, type_ignores=[]),
            str(CREATE_RIG),
            "exec",
        ),
        namespace,
    )
    return namespace


def test_fixed_face_control_roots_are_not_external_systems() -> None:
    helpers = _ownership_helpers()
    is_owned = helpers["_is_builder_owned_extension_root"]
    known_face_bases = {
        "baby_neck",
        "l_chin",
        "l_mandible",
        "nose_root",
        "r_chin",
        "r_mandible",
    }

    for stem in known_face_bases:
        assert is_owned(
            "|rig|{}_ctrl_pad".format(stem),
            owned=set(),
            known_bases=known_face_bases,
        )


def test_unrelated_custom_control_system_remains_external() -> None:
    helpers = _ownership_helpers()
    is_owned = helpers["_is_builder_owned_extension_root"]

    assert not is_owned(
        "|rig|cape_secondary_ctrl_pad",
        owned=set(),
        known_bases={"baby_neck", "nose_root"},
    )
    assert not is_owned(
        "|rig|custom_face_solver_grp",
        owned=set(),
        known_bases={"custom_face_solver"},
    )
