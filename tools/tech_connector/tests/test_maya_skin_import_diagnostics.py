from __future__ import annotations

import ast
from collections import OrderedDict
import difflib
from pathlib import Path
import re


TOOLS_ROOT = Path(__file__).resolve().parents[2]
SKINNING_UTILS = TOOLS_ROOT / "maya_tools" / "Rigging" / "skinning_utils.py"
HIK_UI = TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"


def _diagnostic_helpers():
    """Load the pure name helpers without requiring a Maya Python runtime."""
    tree = ast.parse(SKINNING_UTILS.read_text(encoding="utf-8"))
    helper_names = {
        "_influence_leaf_name",
        "_influence_match_key",
        "_find_similar_scene_influences",
        "_format_missing_influence_failure",
        "_rename_missing_influence_matches",
    }
    helper_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    namespace = {
        "OrderedDict": OrderedDict,
        "difflib": difflib,
        "re": re,
    }
    exec(
        compile(
            ast.Module(body=helper_nodes, type_ignores=[]),
            str(SKINNING_UTILS),
            "exec",
        ),
        namespace,
    )
    return namespace


def test_skin_import_suggests_namespaced_and_similarly_named_joints() -> None:
    helpers = _diagnostic_helpers()
    suggestions = helpers["_find_similar_scene_influences"](
        ["origin", "neck1", "l_brow1", "l_knee_twist1", "absent_joint"],
        [
            "|Coolaid|CoolaidDefA:origin1",
            "|Coolaid|CoolaidDefA:neck",
            "|Coolaid|CoolaidDefA:l_brow_01",
            "|Coolaid|CoolaidDefA:l_knee1_twist",
            "|Coolaid|CoolaidDefA:pelvis",
        ],
    )

    assert suggestions["origin"] == ["origin1"]
    assert suggestions["neck1"] == ["neck"]
    assert suggestions["l_brow1"] == ["l_brow_01"]
    assert suggestions["l_knee_twist1"] == ["l_knee1_twist"]
    assert suggestions["absent_joint"] == []

    full_paths = helpers["_find_similar_scene_influences"](
        ["neck1"],
        ["|Coolaid|CoolaidDefA:neck"],
        short_names=False,
    )
    assert full_paths["neck1"] == ["|Coolaid|CoolaidDefA:neck"]


def test_skin_import_failure_names_every_missing_influence_and_reason() -> None:
    helpers = _diagnostic_helpers()
    message = helpers["_format_missing_influence_failure"](
        "body_geo",
        ["neck1", "absent_joint"],
        {
            "neck1": ["neck"],
            "absent_joint": [],
        },
    )

    assert "2 required skin influence(s) are missing" in message
    assert "neck1" in message
    assert "neck1 (similar scene joint: neck)" in message
    assert "absent_joint (no similar scene joint found)" in message
    assert "Skin weights were not imported" in message


def test_confirmed_joint_renames_keep_namespace_and_process_children_first() -> None:
    helpers = _diagnostic_helpers()

    class FakeCmds:
        def __init__(self):
            self.renames = []
            self.undo_calls = []

        def undoInfo(self, **kwargs):
            self.undo_calls.append(kwargs)

        def rename(self, source, target):
            self.renames.append((source, target))
            return target

        def undo(self):
            raise AssertionError("Successful renames should not roll back")

    fake_cmds = FakeCmds()
    helpers["_rename_missing_influence_matches"].__globals__["cmds"] = fake_cmds
    renamed, failures = helpers["_rename_missing_influence_matches"]({
        "neck1": "|rig|CoolaidDefA:neck",
        "l_brow1": "|rig|CoolaidDefA:neck|CoolaidDefA:l_brow_01",
    })

    assert not failures
    assert fake_cmds.renames == [
        (
            "|rig|CoolaidDefA:neck|CoolaidDefA:l_brow_01",
            "CoolaidDefA:l_brow1",
        ),
        ("|rig|CoolaidDefA:neck", "CoolaidDefA:neck1"),
    ]
    assert renamed == {
        "l_brow1": "CoolaidDefA:l_brow1",
        "neck1": "CoolaidDefA:neck1",
    }
    assert fake_cmds.undo_calls == [
        {"openChunk": True, "chunkName": "Rename Skin Import Influences"},
        {"closeChunk": True},
    ]


def test_skin_import_ui_distinguishes_failed_and_partial_results() -> None:
    skinning_source = SKINNING_UTILS.read_text(encoding="utf-8")
    ui_source = HIK_UI.read_text(encoding="utf-8")

    assert '"failure_reports": failure_reports' in skinning_source
    assert '"reason": "missing_influences"' in skinning_source
    assert "Skin Import Failed" in ui_source
    assert "Skin Import Partially Complete" in ui_source
    assert "Possible match" in ui_source
    assert "Rename Matches and Import" in ui_source
    assert "Skin Import Needs Joint Matches" in ui_source
