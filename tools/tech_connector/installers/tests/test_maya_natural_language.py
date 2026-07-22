from router.command_router import CommandRouter


def test_maya_natural_create_cube_translates_to_polycube():
    code = CommandRouter().maya_natural_language_to_python("create a cube in maya")

    assert "import maya.cmds as cmds" in code
    assert "cmds.polyCube" in code
    assert "cmds.select" in code


def test_maya_natural_create_polycube_translates_to_polycube():
    code = CommandRouter().maya_natural_language_to_python("create a polyCube in the current Maya scene")

    assert "cmds.polyCube" in code


def test_maya_natural_named_sphere_uses_name():
    code = CommandRouter().maya_natural_language_to_python("make a sphere in Maya named heroBall")

    assert "cmds.polySphere" in code
    assert "name='heroBall'" in code


def test_non_maya_text_is_not_translated():
    assert CommandRouter().maya_natural_language_to_python("create a cube") == ""


def test_maya_natural_parent_constraint_multiple_targets():
    code = CommandRouter().maya_natural_language_to_python(
        "in Maya parent constrain the pelvis_ctrl to x, y, and z objects"
    )

    assert "cmds.parentConstraint" in code
    assert "driven = 'pelvis_ctrl'" in code
    assert "targets = ['x', 'y', 'z']" in code
    assert "maintainOffset=True" in code
    assert "cmds.objExists" in code


def test_maya_natural_orient_constraint_without_offset():
    code = CommandRouter().maya_natural_language_to_python(
        "maya orient constrain head_ctrl to neck_ctrl without offset"
    )

    assert "cmds.orientConstraint" in code
    assert "driven = 'head_ctrl'" in code
    assert "targets = ['neck_ctrl']" in code
    assert "maintainOffset=False" in code


def test_maya_direct_natural_command_can_omit_maya_word():
    code = CommandRouter().maya_natural_language_to_python(
        "parent constrain pelvis_ctrl to world_ctrl",
        require_maya_word=False,
    )

    assert "cmds.parentConstraint" in code
