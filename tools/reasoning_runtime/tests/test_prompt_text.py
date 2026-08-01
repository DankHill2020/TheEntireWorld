from __future__ import annotations

import unittest

from reasoning_runtime import normalize_prompt_text


class PromptTextTests(unittest.TestCase):
    def test_normalizes_spacing_and_common_typos(self):
        self.assertEqual(normalize_prompt_text("waht   is teh file"), "what is the file")


if __name__ == "__main__":
    unittest.main()
