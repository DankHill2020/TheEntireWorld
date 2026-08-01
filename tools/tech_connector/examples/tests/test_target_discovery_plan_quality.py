"""Unit tests for dynamic entity detection and plan quality in TargetDiscoveryEditProvider."""

from unittest.mock import MagicMock
from tech_connector.engine.providers import TargetDiscoveryEditProvider
from tech_connector.engine.request_context import RequestContext


def test_qtablewidget_dynamic_plan_synthesis():
    provider = TargetDiscoveryEditProvider()
    context = RequestContext(text="plan a strategy first for adding a QTableWidget class in custom_qt.custom_widgets, no edits yet")

    selected_candidate = {
        "path": r"C:\depot\tools\custom_qt\custom_widgets.py",
        "score": 470.0,
        "symbols": [],
    }
    ordered_candidates = [
        {"path": r"C:\depot\tools\custom_qt\custom_widgets.py", "score": 470.0, "evidence_confidence": 0.86},
        {"path": r"C:\depot\tools\maya_tools\Rigging\create_rig.py", "score": 230.0, "evidence_confidence": 0.50},
    ]
    resolution = {
        "confidence": 0.86,
        "reasons": [
            "Candidate is open in the editor.",
            "Underlying provider score=529.000.",
            "Candidate is editable source (.py).",
        ],
    }

    plan_text = provider._plan_text(context, {}, selected_candidate, ordered_candidates, resolution)

    # 1. Verify QTableWidget subclass sketch is generated
    assert "class CustomTableWidget(QtWidgets.QTableWidget):" in plan_text
    assert "QtWidgets.QTableWidgetItem" in plan_text

    # 2. Verify NO raw telemetry scores leak to user display
    assert "Underlying provider score=" not in plan_text
    assert "Target confidence:" not in plan_text
    assert "Evidence score:" not in plan_text
    assert "(score 470.0)" not in plan_text
    assert "confidence 0.86" not in plan_text

    # 3. Verify clean human-readable reasons
    assert "Selected file is active in the workspace editor." in plan_text
    assert "Target is editable Python source file." in plan_text


def test_dataclass_dynamic_plan_synthesis():
    provider = TargetDiscoveryEditProvider()
    context = RequestContext(text="plan strategy for adding an AssetMetadata dataclass in assets.py")
    selected_candidate = {"path": r"C:\depot\tools\assets.py", "score": 300.0}
    ordered_candidates = [selected_candidate]
    resolution = {"confidence": 0.90, "reasons": ["Target matches expected implementation module."]}

    plan_text = provider._plan_text(context, {}, selected_candidate, ordered_candidates, resolution)

    assert "@dataclass" in plan_text
    assert "class AssetMetadata:" in plan_text
    assert "to_dict" in plan_text or "dataclass" in plan_text


def test_enum_dynamic_plan_synthesis():
    provider = TargetDiscoveryEditProvider()
    context = RequestContext(text="plan strategy for adding an AnimationState enum in anim_controller.py")
    selected_candidate = {"path": r"C:\depot\tools\anim_controller.py", "score": 350.0}
    ordered_candidates = [selected_candidate]
    resolution = {"confidence": 0.85, "reasons": ["Target is editable Python source file."]}

    plan_text = provider._plan_text(context, {}, selected_candidate, ordered_candidates, resolution)

    assert "class AnimationState(enum.Enum):" in plan_text


def test_function_dynamic_plan_synthesis():
    provider = TargetDiscoveryEditProvider()
    context = RequestContext(text="plan strategy for adding a parse_rig_metadata helper function in rigging_utils.py")
    selected_candidate = {"path": r"C:\depot\tools\rigging_utils.py", "score": 280.0}
    ordered_candidates = [selected_candidate]
    resolution = {"confidence": 0.88, "reasons": ["Selected file is active in the workspace editor."]}

    plan_text = provider._plan_text(context, {}, selected_candidate, ordered_candidates, resolution)

    assert "def parse_rig_metadata(" in plan_text
