from unittest.mock import Mock

from reasoning_runtime.engine.progress_events import EngineResult
from reasoning_runtime.engine.request_context import RequestContext

from tech_connector.engine.request_engine import RequestEngine
from tech_connector.app.main_window_workflow_authoring_mixin import (
    MainWindowWorkflowAuthoringMixin,
)
from tech_connector.services.reasoning.clarification_service import build_confirmation


def test_approved_preclassified_route_dispatches_without_reclassification():
    engine = RequestEngine.__new__(RequestEngine)
    engine.progress = lambda _event: None
    engine.activity = lambda _event: None
    engine._dispatch_preclassified = Mock(
        return_value=EngineResult("answer", "DCC Execution", "executed")
    )
    route = {
        "route": "dcc_execute",
        "execution_route": "dcc.execution_pipeline",
        "approved": True,
        "requires_confirmation": False,
    }
    context = RequestContext(
        text="create the rig",
        extras={"prompt_route_decision": route},
    )

    result = RequestEngine.process.__wrapped__(engine, context)

    assert result.text == "executed"
    engine._dispatch_preclassified.assert_called_once_with(route, context)


def test_maya_script_confirmation_explains_effect_without_dumping_code():
    code = """root_joint = 'origin'
body, face = setup_hik.create_rig_mapping(root_joint=root_joint)
create_rig.create_rig_from_mapping(body, face)
"""
    result = build_confirmation(
        decision={"route": "dcc_execute", "host": "maya", "requires_confirmation": True},
        context=RequestContext(text="create the rig"),
        execution_request={
            "callable_name": "ai_studio.maya.generated.script_run",
            "target_identifier": "script.run",
            "execution_environment": "maya",
            "keyword_args": {"code": code, "timeout": 180},
            "mutation_scope": "dcc_scene_mutation",
            "risk_level": "high",
        },
        dispatch_result={
            "confirmation_request": {
                "operation": "script.run",
                "mutation_scope": "dcc_scene_mutation",
                "risk_level": "high",
            }
        },
    )

    assert "Approval required: Create a control rig in Maya" in result.text
    assert "Use `origin` as the root joint" in result.text
    assert "Affected scope: the current Maya scene" in result.text
    assert "Undo/recovery:" in result.text
    assert "Why you are being asked:" in result.text
    assert "Approval ID:" in result.text
    assert "create_rig.create_rig_from_mapping(body, face)" not in result.text
    assert "exact prepared execution" in result.text
    assert result.pending_state["confirmation"]["schema"] == "tech_connector.approval_prompt.v1"
    assert result.pending_state["confirmation"]["prompt_text"] == result.text


def test_confirmation_redacts_secrets_and_has_a_stable_operation_id():
    kwargs = {
        "asset_path": "/Game/Characters/BP_Hero",
        "api_token": "do-not-display",
    }
    call = dict(
        decision={"route": "dcc_execute", "host": "unreal", "requires_confirmation": True},
        context=RequestContext(text="patch the hero graph"),
        execution_request={
            "callable_name": "tech_connector.unreal.graph.patch",
            "target_identifier": "graph.patch",
            "execution_environment": "unreal",
            "keyword_args": kwargs,
            "mutation_scope": "dcc_scene_mutation",
            "risk_level": "high",
        },
        dispatch_result={
            "confirmation_request": {
                "operation": "unreal_graph_patch",
                "target_asset": "/Game/Characters/BP_Hero",
                "target_graph": "EventGraph",
                "preview": {"operation_count": 2},
                "mutation_scope": "dcc_scene_mutation",
                "risk_level": "high",
            }
        },
    )

    first = build_confirmation(**call)
    second = build_confirmation(**call)

    assert "Apply an Unreal graph patch to /Game/Characters/BP_Hero / EventGraph" in first.text
    assert "Apply 2 graph operation(s)" in first.text
    assert "do-not-display" not in first.text
    assert first.pending_state["confirmation"]["approval_id"] == second.pending_state["confirmation"]["approval_id"]


def test_unchanged_pipeline_warning_is_reported_once():
    issues = [
        {
            "step_id": "rig",
            "input": "root_joint",
            "message": "rig.root_joint needs a value or data connection.",
        }
    ]

    class View:
        def refresh_data_flow_warnings(self):
            return list(issues)

    class Window(MainWindowWorkflowAuthoringMixin):
        def __init__(self):
            self.wf_node_view = View()
            self.messages = []

        def _report_workflow_builder_event(self, message: str):
            self.messages.append(message)

    window = Window()
    window._refresh_pipeline_data_flow_warnings()
    window._refresh_pipeline_data_flow_warnings()

    assert window.messages == [
        "Pipeline data flow needs attention: 1 input(s) need a value or connection."
    ]
