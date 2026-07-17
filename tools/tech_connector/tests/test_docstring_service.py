import unittest

from tech_connector.services.docstring_service import add_missing_docstrings, looks_like_docstring_request


class DocstringServiceTests(unittest.TestCase):
    def test_adds_docstring_to_missing_function(self):
        source = "def create_diamond_ctrl(name, size=1.0, normal=(0, 1, 0)):\n    return name\n"

        result = add_missing_docstrings(source)

        self.assertTrue(result.changed)
        self.assertIn('    """', result.source)
        self.assertIn("    Creates diamond ctrl.", result.source)
        self.assertIn("    :param name: name", result.source)
        self.assertIn("    :param size: local size mult", result.source)
        self.assertIn("    :param normal: relative direction", result.source)
        self.assertIn("    :return: result", result.source)

    def test_repairs_existing_docstring_missing_params(self):
        source = '''def create_full_rig(arm_joints=None, leg_joints=None):
    """
        Builds the entire character rig by coordinating modular setup builders.
    :param arm_joints: list of mapped arm joints
    """
    return {}
'''

        result = add_missing_docstrings(source)

        self.assertTrue(result.changed)
        self.assertIn(":param arm_joints: list of mapped arm joints", result.source)
        self.assertIn(":param leg_joints: list of leg joints", result.source)
        self.assertIn(":return: result", result.source)
        self.assertEqual(result.updated_existing, ["create_full_rig"])

    def test_expands_one_line_docstring_when_repairing(self):
        source = 'def get_value(data, key):\n    """Gets a value."""\n    return data.get(key)\n'

        result = add_missing_docstrings(source)

        self.assertTrue(result.changed)
        self.assertIn('    """\n        Gets a value.\n    :param data: data\n    :param key: key\n    :return: result\n    """', result.source)

    def test_selection_limits_updates(self):
        source = "def first(value):\n    return value\n\n\ndef second(value):\n    return value\n"

        result = add_missing_docstrings(source, selection_start_line=1, selection_end_line=2)

        self.assertTrue(result.changed)
        self.assertIn("First.", result.source)
        self.assertNotIn("Second.", result.source)
        self.assertEqual(result.skipped_out_of_scope, ["second"])

    def test_detects_docstring_chat_request(self):
        self.assertTrue(looks_like_docstring_request("add docstrings to this file"))
        self.assertTrue(looks_like_docstring_request("generate function documentation"))
        self.assertFalse(looks_like_docstring_request("explain these docs"))


if __name__ == "__main__":
    unittest.main()
