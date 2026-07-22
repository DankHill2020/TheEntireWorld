from pathlib import Path

from knowledge.search import (
    is_editor_generation_request,
    normalize_active_file_additions,
    request_prefers_active_file,
)


def test_add_class_prefers_active_file():
    assert request_prefers_active_file("add a red spin box class")


def test_new_tool_can_create_files():
    assert not request_prefers_active_file("make a new tool for exporting animations")


def test_explanation_is_not_edit_generation():
    assert not is_editor_generation_request("what does this class do?")


def test_widget_addition_is_edit_generation():
    assert is_editor_generation_request("add a custom spinbox widget")


def test_documentation_requests_are_edit_generation():
    assert is_editor_generation_request("document this class")
    assert is_editor_generation_request("write a README for this tool")
    assert is_editor_generation_request("add docstrings to this module")


def test_created_definition_is_folded_into_active_file(tmp_path):
    active = tmp_path / "custom_widgets.py"
    active_text = "class ExistingWidget:\n    pass\n"
    changes = [
        {
            "action": "create",
            "path": str(tmp_path / "CustomRedSpinBox.py"),
            "new_content": "class CustomRedSpinBox:\n    pass\n",
        }
    ]

    normalized = normalize_active_file_additions(
        changes,
        str(active),
        active_text,
        "add a red spin box class",
    )

    assert normalized == [
        {
            "action": "modify",
            "path": str(Path(active).resolve()),
            "original_content": active_text,
            "new_content": "class ExistingWidget:\n    pass\n\n\nclass CustomRedSpinBox:\n    pass\n",
        }
    ]
