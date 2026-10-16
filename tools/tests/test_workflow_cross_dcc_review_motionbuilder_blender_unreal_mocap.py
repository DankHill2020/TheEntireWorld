import ast
from pathlib import Path


def test_workflow_cross_dcc_review_motionbuilder_blender_unreal_mocap_defines_callable():
    source = Path('C:\\depot\\tools\\workflows\\cross_dcc\\review_motionbuilder_blender_unreal_mocap.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    assert any(getattr(node, 'name', '') == 'review_motionbuilder_blender_unreal_mocap' for node in tree.body)
