import ast
from pathlib import Path


def test_workflow_cross_dcc_review_substance_tech_connector_texture_publish_defines_callable():
    source = Path('C:\\depot\\tools\\workflows\\cross_dcc\\review_substance_tech_connector_texture_publish.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    assert any(getattr(node, 'name', '') == 'review_substance_tech_connector_texture_publish' for node in tree.body)
