from __future__ import annotations

from tech_connector.services.action_execution_engine import ActionExecutionEngine


def test_empty_dcc_execution_is_invalid_and_cannot_downgrade_approval() -> None:
    plan = {
        "goal": "Build an Unreal animation system",
        "intent": "workflow_pipeline",
        "actions": [
            {
                "id": "execute_unresolved",
                "type": "execute_dcc",
                "args": {"host": "unreal", "operation": "", "callable": "", "params": {}},
                "requires_approval": False,
            }
        ],
    }
    engine = ActionExecutionEngine()

    validation = engine.validate_plan(plan)
    approval = engine.analyze_approval_requirements(plan)

    assert not validation["valid"]
    assert any("requires an operation" in error for error in validation["errors"])
    assert approval["approval_required"]
    assert approval["read_only_actions"] == []
    assert approval["mutating_actions"][0]["action_id"] == "execute_unresolved"
