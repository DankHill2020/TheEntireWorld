import unittest

from tech_connector.scripts.prompt_smoke_ollama import (
    _assess_output,
    _choose_installed_synthesis_model,
    _requested_code_contract_failures,
)


class TestPromptSmokeOllama(unittest.TestCase):
    def test_missing_standard_model_prefers_installed_light_coder(self):
        model = _choose_installed_synthesis_model(
            "llama3:latest",
            ["qwen3:14b", "qwen2.5-coder:7b", "qwen2.5-coder:14b"],
            model_tier="standard",
        )

        self.assertEqual("qwen2.5-coder:7b", model)

    def test_strong_model_respects_seven_billion_parameter_ceiling(self):
        model = _choose_installed_synthesis_model(
            "missing:latest",
            ["qwen2.5-coder:7b", "qwen3:14b"],
            model_tier="strong",
        )

        self.assertEqual("qwen2.5-coder:7b", model)

    def test_complete_requested_qt_code_satisfies_dynamic_contract(self):
        prompt = (
            "Write complete runnable PySide6 code for a MaterialDialog QWidget class with "
            "a QPushButton generate_material_btn and QLabel status_label. Connect clicked "
            "to a create_material method with a real body and include a __main__ entry point."
        )
        output = """
```python
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

class MaterialDialog(QWidget):
    def __init__(self):
        super().__init__()
        self.status_label = QLabel("Ready", self)
        self.generate_material_btn = QPushButton("Generate", self)
        self.generate_material_btn.clicked.connect(self.create_material)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.generate_material_btn)

    def create_material(self):
        self.status_label.setText("Created")

if __name__ == "__main__":
    app = QApplication([])
    dialog = MaterialDialog()
    dialog.show()
    app.exec()
```
"""

        self.assertEqual([], _requested_code_contract_failures(prompt, output))
        self.assertEqual(("good", ["complete_code_contract"]), _assess_output(output, prompt))

    def test_refusal_cannot_pass_a_self_contained_code_request(self):
        prompt = (
            "Write complete runnable PySide6 code for a MaterialDialog QWidget class with "
            "a QPushButton and a create_material method with a real body and __main__ entry point."
        )
        failures = _requested_code_contract_failures(
            prompt,
            "No actionable route was found. Clarification needed before an implementation plan can be created.",
        )

        self.assertIn("code_request_returned_no_declarations", failures)
        self.assertIn("missing_requested_class_MaterialDialog", failures)
        self.assertIn("missing_requested_callable_create_material", failures)
        self.assertIn("self_contained_code_request_was_refused", failures)

    def test_placeholder_requested_method_is_rejected(self):
        prompt = "Create a Worker class with a run method containing a real body and no placeholder."
        output = """
```python
class Worker:
    def run(self):
        ...
```
"""

        failures = _requested_code_contract_failures(prompt, output)

        self.assertIn("placeholder_requested_callable_run", failures)
        self.assertIn("placeholder_callable_run", failures)


if __name__ == "__main__":
    unittest.main()
