import ast
from pathlib import Path


def test_workflow_cross_dcc_review_houdini_unreal_fx_mesh_publish_defines_callable():
    source = Path('C:\\depot\\tools\\workflows\\cross_dcc\\review_houdini_unreal_fx_mesh_publish.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    assert any(getattr(node, 'name', '') == 'review_houdini_unreal_fx_mesh_publish' for node in tree.body)
