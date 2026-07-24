import ast
import unittest

from tech_connector.services.workflow_service import extract_python_code, first_function_name


class TestPipelinePythonPasteSafety(unittest.TestCase):
    def test_markdown_fenced_pipeline_code_is_safe_to_compile(self) -> None:
        pasted = '''```python
"""Generated pipeline.
Goal: pasted from chat
"""

def pasted_pipeline(step1_value=None):
    return {"value": step1_value}
```'''

        cleaned = extract_python_code(pasted)

        self.assertFalse(cleaned.lstrip().startswith("```"))
        ast.parse(cleaned)
        self.assertEqual("pasted_pipeline", first_function_name(cleaned))


if __name__ == "__main__":
    unittest.main()
