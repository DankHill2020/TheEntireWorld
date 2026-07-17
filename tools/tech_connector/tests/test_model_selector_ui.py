from pathlib import Path
import unittest


class ModelSelectorUiTests(unittest.TestCase):
    def test_model_selector_is_not_freeform_editable(self):
        source = Path("app/main_window_ui.py").read_text(encoding="utf-8")
        marker = "self.model_box = QComboBox()"
        start = source.index(marker)
        end = source.index("self._seen_models = set()", start)
        block = source[start:end]

        self.assertIn("self.model_box.setEditable(False)", block)
        self.assertNotIn("self.model_box.setEditable(True)", block)


if __name__ == "__main__":
    unittest.main()
