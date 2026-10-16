from __future__ import annotations

import ast
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[2]
CREATE_RIG = TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig.py"


def _literal_assignment(name):
    tree = ast.parse(CREATE_RIG.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Assignment not found: {}".format(name))


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
                and target.id in {
                    "_BUILDER_CONTROL_ROOT_SUFFIXES",
                    "USER_AUTHORED_EXTENSION_STEMS",
                }
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


def test_legacy_face_roots_remain_owned_when_the_live_pad_is_missing() -> None:
    roots = set(_literal_assignment("BUILDER_OWNED_CONTROL_ROOTS"))

    assert {
        "l_chin_ctrl_pad",
        "l_mandible_ctrl_pad",
        "r_chin_ctrl_pad",
        "r_mandible_ctrl_pad",
    }.issubset(roots)
    assert "baby_neck_ctrl_pad" not in roots

    source = CREATE_RIG.read_text(encoding="utf-8")
    ownership_body = source.split("def _metadata_rig_ownership(", 1)[1].split(
        "def record_rig_owned_nodes(", 1
    )[0]
    add_stem = "known_bases.add(_extension_base_name(root_name))"
    lookup_root = "roots = cmds.ls(root_name, long=True) or []"
    assert ownership_body.index(add_stem) < ownership_body.index(lookup_root)


def test_unrelated_custom_control_system_remains_external() -> None:
    helpers = _ownership_helpers()
    is_owned = helpers["_is_builder_owned_extension_root"]

    assert not is_owned(
        "|rig|cape_secondary_ctrl_pad",
        owned=set(),
        known_bases={"baby_neck", "nose_root"},
    )
    assert not is_owned(
        "|rig|baby_neck_ctrl_pad",
        owned={"baby_neck_ctrl_pad"},
        known_bases={"baby_neck", "nose_root"},
    )
    assert not is_owned(
        "|rig|custom_face_solver_grp",
        owned=set(),
        known_bases={"custom_face_solver"},
    )
