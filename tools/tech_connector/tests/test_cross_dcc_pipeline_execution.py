from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tech_connector.game_engine.integration.dynamic_pipeline_compiler_service import (
    compile_dynamic_pipeline,
    extract_explicit_operation_mentions,
)
from tech_connector.game_engine.integration.pipeline_operation_runtime_service import (
    execute_pipeline_operation,
)
from tech_connector.game_engine.integration.pipeline_execution_preflight_service import (
    PipelinePreflightError,
    preflight_pipeline_execution,
    resolve_pipeline_session_ports,
)
from tech_connector.services.action_execution_engine import (
    ActionExecutionEngine,
    ExecutionContext,
)
from tech_connector.services.action_planner_service import workflow_plan_from_action_graph
from tech_connector.services.chat_report_service import format_action_plan_chat_report
from tech_connector.services.workflow_codegen_service import generate_pipeline_code_from_graph


def test_explicit_function_list_preserves_every_registered_request_in_order():
    prompt = (
        "Transfer a static mesh from Maya through Blender to Unreal. Functions: "
        "maya.scene.ls, maya.animation.export, blender.io.import_fbx, "
        "blender.pipeline.process_meshes_for_transfer, blender.blender.export_fbx, "
        "unreal_tools.asset_transfer_adapter.import_fbx_verified, "
        "unreal_tools.asset_transfer_adapter.registry_readback."
    )

    plan = compile_dynamic_pipeline(prompt)
    operations = [stage["operation"] for stage in plan["stages"]]

    requested = [
        "scene.ls",
        "animation.export",
        "io.import_fbx",
        "pipeline.process_meshes_for_transfer",
        "blender.export_fbx",
        "unreal_tools.asset_transfer_adapter.import_fbx_verified",
        "unreal_tools.asset_transfer_adapter.registry_readback",
    ]
    assert all(operation in operations for operation in requested)
    assert [operations.index(operation) for operation in requested] == sorted(
        operations.index(operation) for operation in requested
    )
    assert len(plan["explicit_function_requests"]) == len(requested)
    assert not plan["unresolved_function_requests"]


def test_unknown_named_function_is_a_blocking_capability_gap():
    plan = compile_dynamic_pipeline(
        "Export a mesh from Maya to Unreal. Functions: maya.animation.export, "
        "unreal.magic_import_everything."
    )

    assert plan["success"] is False
    assert plan["unresolved_function_requests"] == ["unreal.magic_import_everything"]
    assert any(gap["kind"] == "unknown_requested_function" for gap in plan["gaps"])


def test_explicit_lazy_unreal_api_function_uses_contract_resolver(monkeypatch):
    def resolve(query, *, host="", project_root=None):
        if query != "unreal.EditorAssetLibrary.list_assets" or host != "unreal":
            return {"ok": False}
        return {
            "ok": True,
            "contract": {
                "key": "unreal.base_unreal_python_api.EditorAssetLibrary.list_assets",
                "host": "unreal",
                "operation": query,
                "label": query,
                "callable": query,
                "provider": "unreal_base_python_api",
                "role": "operate",
                "required": ("directory_path",),
                "produces": ("result",),
                "implementation_state": "implemented_python",
            },
        }

    monkeypatch.setattr(
        "tech_connector.game_engine.integration.dynamic_pipeline_compiler_service.resolve_operation_contract",
        resolve,
    )
    mentions, unresolved = extract_explicit_operation_mentions(
        "From Maya export to Unreal, then call `unreal.EditorAssetLibrary.list_assets`."
    )

    assert unresolved == []
    assert any(row["contract"].callable == "unreal.EditorAssetLibrary.list_assets" for row in mentions)


def test_explicit_functions_remain_a_subsequence_in_the_users_order():
    plan = compile_dynamic_pipeline(
        "Transfer from Maya to Unreal. Functions: maya.animation.export, maya.scene.ls, "
        "unreal_tools.asset_transfer_adapter.import_fbx_verified."
    )
    operations = [stage["operation"] for stage in plan["stages"]]

    assert operations.index("animation.export") < operations.index("scene.ls")


def test_transfer_paths_are_concrete_and_runtime_outputs_use_structured_references():
    plan = compile_dynamic_pipeline(
        "Export animation from Maya to C:/tmp/take.fbx and import it into Unreal "
        "using skeleton /Game/Characters/SK_Target, then inspect imported pipeline compatibility."
    )
    unreal_import = next(stage for stage in plan["stages"] if stage["role"] == "import")
    exporter = next(stage for stage in plan["stages"] if stage["role"] == "export")
    inspection = next(
        stage for stage in plan["stages"]
        if stage["operation"] == "animation.inspect_imported_pipeline"
    )

    assert exporter["params"]["export_path"] == "C:/tmp/take.fbx"
    assert unreal_import["params"]["source_file"] == {
        "from_action": exporter["id"],
        "result_path": "fbx_path",
    }
    assert inspection["params"]["imported_paths"] == {
        "from_action": unreal_import["id"],
        "result_path": "imported_paths",
    }
    assert "$fbx_path" not in str(plan["stages"])


def test_action_engine_executes_all_compiled_stages_and_resolves_handoffs(monkeypatch):
    prompt = (
        "Export animation from Maya to C:/tmp/take.fbx and import it into Unreal "
        "using skeleton /Game/Characters/SK_Target, then inspect imported pipeline compatibility."
    )
    plan = compile_dynamic_pipeline(prompt)
    calls = []

    def execute(host, operation, callable_name, params, **kwargs):
        calls.append((host, operation, callable_name, params, kwargs))
        if operation == "unreal_tools.asset_transfer_adapter.import_fbx_verified":
            return {
                "asset_path": "/Game/Imports/Take",
                "imported_paths": ["/Game/Imports/Take"],
                "asset_count": 1,
            }
        if operation == "animation.inspect_imported_pipeline":
            return {
                "compatibility_report": {"compatible": True},
                "animation_paths": params["imported_paths"],
            }
        if operation == "unreal_tools.asset_transfer_adapter.registry_readback":
            return {"assets": params.get("imported_paths", []), "asset_count": 1}
        return {"fbx_path": params.get("export_path", "")}

    monkeypatch.setattr(
        "tech_connector.game_engine.integration.pipeline_operation_runtime_service.execute_pipeline_operation",
        execute,
    )
    context = ExecutionContext(
        approved=True,
        policy={
            "original_prompt": prompt,
            "dcc_session_ports": {"maya": 7001, "unreal": 12347},
            "dcc_retry_attempts": 2,
        },
    )

    report = ActionExecutionEngine().execute_plan(plan, context)

    assert report["status"] == "completed"
    assert len(calls) == len(plan["stages"])
    inspection_call = next(call for call in calls if call[1] == "animation.inspect_imported_pipeline")
    assert inspection_call[3]["imported_paths"] == ["/Game/Imports/Take"]
    assert all(call[4]["session_port"] in {7001, 12347} for call in calls)
    retry_policy = {call[1]: call[4]["retry_safe"] for call in calls}
    assert retry_policy["unreal_tools.asset_transfer_adapter.import_fbx_verified"] is False
    assert retry_policy["animation.export"] is True
    assert retry_policy["animation.inspect_imported_pipeline"] is True


def test_3dsmax_can_participate_in_fbx_engine_pipeline():
    mentions, unresolved = extract_explicit_operation_mentions(
        "Export a static mesh from 3ds Max with 3dsmax.io.export and import it into Unreal."
    )
    plan = compile_dynamic_pipeline(
        "Export a static mesh from 3ds Max with 3dsmax.io.export and import it into Unreal."
    )

    assert unresolved == []
    assert any(row["contract"].operation == "io.export" for row in mentions)
    assert plan["hosts"] == ["3dsmax", "unreal"]
    assert any(stage["operation"] == "io.export" for stage in plan["stages"])


def test_missing_upstream_artifact_blocks_downstream_call(monkeypatch):
    prompt = (
        "Export animation from Maya to C:/tmp/take.fbx and import it into Unreal "
        "using skeleton /Game/Characters/SK_Target, then inspect imported pipeline compatibility."
    )
    plan = compile_dynamic_pipeline(prompt)
    calls = []

    def execute(host, operation, callable_name, params, **kwargs):
        calls.append(operation)
        if operation == "animation.export":
            return {"fbx_path": params["export_path"]}
        if operation == "unreal_tools.asset_transfer_adapter.import_fbx_verified":
            return {"asset_path": "/Game/Imports/Take", "asset_count": 1}
        return {"ok": True}

    monkeypatch.setattr(
        "tech_connector.game_engine.integration.pipeline_operation_runtime_service.execute_pipeline_operation",
        execute,
    )
    report = ActionExecutionEngine().execute_plan(
        plan,
        ExecutionContext(approved=True, policy={"original_prompt": prompt}),
    )

    assert report["status"] == "partial_failure"
    assert "animation.inspect_imported_pipeline" not in calls
    failed = next(
        value for value in report["results"].values()
        if value.get("failure_category") == "dependency_failure"
    )
    assert "imported_paths" in failed["exception_message"]


def test_dcc_can_target_the_tech_connector_engine_project(tmp_path):
    plan = compile_dynamic_pipeline(
        "Export a static mesh from Blender into the Tech Connector engine.",
        project_root=str(tmp_path),
    )

    assert plan["hosts"] == ["blender", "tech_connector"]
    exporter = next(stage for stage in plan["stages"] if stage["host"] == "blender")
    engine_import = next(stage for stage in plan["stages"] if stage["host"] == "tech_connector")
    assert engine_import["operation"] == "asset.import_interchange"
    assert engine_import["params"]["project_root"] == str(tmp_path)
    assert exporter["params"]["filepath"].endswith(".fbx")
    assert engine_import["params"]["source_file"] == {
        "from_action": exporter["id"],
        "result_path": "fbx_path",
    }


def test_tech_connector_engine_import_executes_and_returns_stable_asset_identity(tmp_path):
    project = tmp_path / "Project"
    project.mkdir()
    source = tmp_path / "handoff.fbx"
    source.write_bytes(b"mock-fbx-payload")

    result = execute_pipeline_operation(
        "tech_connector",
        "asset.import_interchange",
        "tech_connector.game_engine.integration.tech_connector_pipeline_adapter.import_interchange_asset",
        {
            "source_file": str(source),
            "project_root": str(project),
            "folder": "Assets/Imported",
        },
    )

    assert result["asset_id"].startswith("tc.asset.")
    assert result["asset_type"] == "tc.static_mesh"
    assert result["asset_count"] == 1
    assert (project / "Assets" / "Imported" / "handoff.fbx").is_file()
    assert result["imported_paths"] == [result["asset_path"]]


def test_tech_connector_engine_import_accepts_multi_file_texture_handoff(tmp_path):
    project = tmp_path / "Project"
    project.mkdir()
    sources = []
    for name in ("character_basecolor.png", "character_normal.png"):
        path = tmp_path / name
        path.write_bytes(b"mock-image")
        sources.append(str(path))

    result = execute_pipeline_operation(
        "tech_connector",
        "asset.import_interchange",
        "tech_connector.game_engine.integration.tech_connector_pipeline_adapter.import_interchange_asset",
        {"source_file": sources, "project_root": str(project), "folder": "Assets/Textures"},
    )

    assert result["asset_count"] == 2
    assert len(result["asset_ids"]) == 2
    assert len(set(result["asset_ids"])) == 2
    assert all(Path(path).is_file() for path in result["asset_paths"])


def test_generated_pipeline_code_executes_the_same_typed_handoffs(monkeypatch):
    prompt = (
        "Export animation from Maya to C:/tmp/take.fbx and import it into Unreal "
        "using skeleton /Game/Characters/SK_Target, then inspect imported pipeline compatibility."
    )
    plan = compile_dynamic_pipeline(prompt)
    workflow = workflow_plan_from_action_graph(plan)
    code = generate_pipeline_code_from_graph("saved_cross_dcc", prompt, workflow["steps"])
    calls = []

    def execute(host, operation, callable_name, params, **kwargs):
        calls.append((operation, params))
        if operation == "unreal_tools.asset_transfer_adapter.import_fbx_verified":
            return {"asset_path": "/Game/Take", "imported_paths": ["/Game/Take"], "asset_count": 1}
        if operation == "animation.inspect_imported_pipeline":
            return {"compatibility_report": {"compatible": True}, "animation_paths": params["imported_paths"]}
        if operation == "unreal_tools.asset_transfer_adapter.registry_readback":
            return {"assets": params["imported_paths"], "asset_count": 1}
        return {"fbx_path": params["export_path"]}

    monkeypatch.setattr(
        "tech_connector.game_engine.integration.pipeline_operation_runtime_service.execute_pipeline_operation",
        execute,
    )
    namespace = {}
    exec(compile(code, "<saved_cross_dcc>", "exec"), namespace)
    result = namespace["saved_cross_dcc"](require_live_preflight=False)

    assert result["asset_count"] == 1
    inspection = next(params for operation, params in calls if operation == "animation.inspect_imported_pipeline")
    assert inspection["imported_paths"] == ["/Game/Take"]
    assert "'from_action'" not in code
    assert "outputs['step2']['imported_paths']" in code
    assert "resolve_pipeline_session_ports" in code
    assert "session_port=_tc_session_ports.get" in code
    assert "callables_by_host=_tc_pipeline_callables" in code


def test_generated_pipeline_preflights_all_hosts_before_first_stage(monkeypatch):
    prompt = "Export a static mesh from Blender into the Tech Connector engine."
    plan = compile_dynamic_pipeline(prompt, project_root="C:/depot/tools")
    workflow = workflow_plan_from_action_graph(plan)
    code = generate_pipeline_code_from_graph("saved_preflight", prompt, workflow["steps"])
    calls = []

    monkeypatch.setattr(
        "tech_connector.game_engine.integration.pipeline_execution_preflight_service.resolve_pipeline_session_ports",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Blender is not ready")),
    )
    monkeypatch.setattr(
        "tech_connector.game_engine.integration.pipeline_operation_runtime_service.execute_pipeline_operation",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {},
    )
    namespace = {}
    exec(compile(code, "<saved_preflight>", "exec"), namespace)

    with pytest.raises(RuntimeError, match="Blender is not ready"):
        namespace["saved_preflight"]()
    assert calls == []


class _PreflightBridge:
    def __init__(self, host, ports, *, identity=True, unavailable=()):
        self.host = host
        self.ports = list(ports)
        self.identity = identity
        self.unavailable = set(unavailable)
        self._forced_port = None

    def find_ports(self):
        return list(self.ports)

    def session_info(self, port=None, timeout=1.0):
        return {
            "ok": int(port or 0) in self.ports,
            "port": int(port or 0),
            "session_id": f"{self.host}:{port}" if self.identity else "",
            "timeout": timeout,
        }

    def execute_on_port(self, code, *, port, timeout=1.0):
        line = next(
            value for value in code.splitlines()
            if value.startswith("_TC_CALLABLE_PATHS = ")
        )
        names = ast.literal_eval(line.split(" = ", 1)[1])
        payload = {
            "schema": "tech_connector.callable_probe.v1",
            "callables": {
                name: {
                    "available": name not in self.unavailable,
                    "error": "missing in host" if name in self.unavailable else "",
                }
                for name in names
            },
        }
        return True, json.dumps(payload)

    def execute_python(self, source, timeout=1.0, reset_globals=True):
        ok, payload = self.execute_on_port(
            source, port=int(self._forced_port or 0), timeout=timeout,
        )
        return {"ok": ok, "python_stdout": payload, "reset_globals": reset_globals}


def test_pipeline_preflight_covers_explicit_functions_and_typed_handoffs():
    plan = compile_dynamic_pipeline(
        "Export animation from Maya to C:/tmp/take.fbx and import it into Unreal "
        "using skeleton /Game/Characters/SK_Target. Functions: maya.animation.export, "
        "unreal_tools.asset_transfer_adapter.import_fbx_verified."
    )

    preflight = preflight_pipeline_execution(plan)

    assert preflight["ready"] is True
    assert preflight["structural_ready"] is True
    assert preflight["typed_action_count"] == len(plan["stages"])
    assert preflight["explicit_function_count"] == 2
    assert not preflight["errors"]


def test_pipeline_preflight_fails_when_requested_function_is_removed_from_actions():
    plan = compile_dynamic_pipeline(
        "Export animation from Maya to C:/tmp/take.fbx and import it into Unreal "
        "using skeleton /Game/Characters/SK_Target. Functions: maya.animation.export, "
        "unreal_tools.asset_transfer_adapter.import_fbx_verified."
    )
    plan["actions"] = [
        action
        for action in plan["actions"]
        if (action.get("args") or {}).get("operation") != "animation.export"
    ]

    preflight = preflight_pipeline_execution(plan)

    assert preflight["ready"] is False
    assert any(
        error["kind"] == "requested_function_missing_from_plan"
        for error in preflight["errors"]
    )


def test_live_pipeline_preflight_requires_unambiguous_session_selection():
    plan = compile_dynamic_pipeline(
        "Export a static mesh from Blender into the Tech Connector engine.",
        project_root="C:/depot/tools",
    )

    ambiguous = preflight_pipeline_execution(
        plan,
        require_live_sessions=True,
        bridge_factory=lambda host: _PreflightBridge(host, [7002, 7003]),
    )
    pinned = preflight_pipeline_execution(
        plan,
        session_ports={"blender": 7003},
        require_live_sessions=True,
        bridge_factory=lambda host: _PreflightBridge(host, [7002, 7003]),
    )

    assert ambiguous["ready"] is False
    assert ambiguous["hosts"][0]["status"] == "ambiguous_live_sessions"
    assert pinned["ready"] is True
    assert pinned["resolved_session_ports"] == {"blender": 7003}
    assert pinned["callable_probes"][0]["ready"] is True


def test_generated_pipeline_session_resolver_checks_remote_callable_surface():
    callable_name = "blender_tools.io.export_fbx"

    with pytest.raises(PipelinePreflightError, match="unavailable callables"):
        resolve_pipeline_session_ports(
            ["blender"],
            session_ports={"blender": 7021},
            callables_by_host={"blender": [callable_name]},
            bridge_factory=lambda host: _PreflightBridge(
                host, [7021], unavailable={callable_name},
            ),
        )


def test_callable_probe_accepts_valid_legacy_stdout_tuple():
    from tech_connector.game_engine.integration.pipeline_execution_preflight_service import (
        _decode_callable_probe,
    )

    callable_name = "maya_tools.Rigging.validation_proxy.create_rigged_proxy"
    payload = json.dumps({
        "schema": "tech_connector.callable_probe.v1",
        "callables": {callable_name: {"available": True, "error": ""}},
    })

    decoded = _decode_callable_probe((False, payload))

    assert decoded["ok"] is True
    assert decoded["callables"][callable_name]["available"] is True


def test_unreal_callable_probe_stays_pinned_to_selected_bridge():
    callable_name = "unreal_tools.asset_transfer_adapter.import_fbx_verified"
    bridge = _PreflightBridge("unreal", [12349])

    ports = resolve_pipeline_session_ports(
        ["unreal"],
        session_ports={"unreal": 12349},
        callables_by_host={"unreal": [callable_name]},
        bridge_factory=lambda _host: bridge,
    )

    assert ports == {"unreal": 12349}
    assert bridge._forced_port is None


def test_action_engine_live_preflight_blocks_before_first_mutation(monkeypatch):
    plan = compile_dynamic_pipeline(
        "Export a static mesh from Blender into the Tech Connector engine.",
        project_root="C:/depot/tools",
    )
    calls = []

    monkeypatch.setattr(
        "tech_connector.game_engine.integration.pipeline_operation_runtime_service.execute_pipeline_operation",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {},
    )
    report = ActionExecutionEngine().execute_plan(
        plan,
        ExecutionContext(
            approved=True,
            policy={"pipeline_live_preflight": "required"},
            services={
                "pipeline_preflight_bridge_factory": lambda host: _PreflightBridge(host, []),
            },
        ),
    )

    assert report["status"] == "preflight_failed"
    assert calls == []
    assert report["preflight"]["errors"][0]["kind"] == "host_session"


def test_action_engine_blocks_when_callable_is_missing_inside_selected_host(monkeypatch):
    plan = compile_dynamic_pipeline(
        "Export a static mesh from Blender into the Tech Connector engine.",
        project_root="C:/depot/tools",
    )
    blender_callable = next(
        stage["callable"] for stage in plan["stages"] if stage["host"] == "blender"
    )
    calls = []
    monkeypatch.setattr(
        "tech_connector.game_engine.integration.pipeline_operation_runtime_service.execute_pipeline_operation",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {},
    )

    report = ActionExecutionEngine().execute_plan(
        plan,
        ExecutionContext(
            approved=True,
            policy={"pipeline_live_preflight": "required"},
            services={
                "pipeline_preflight_bridge_factory": lambda host: _PreflightBridge(
                    host, [7021], unavailable={blender_callable},
                ),
            },
        ),
    )

    assert report["status"] == "preflight_failed"
    assert calls == []
    assert report["preflight"]["structural_ready"] is True
    assert report["preflight"]["live_ready"] is False
    error = next(item for item in report["preflight"]["errors"] if item["kind"] == "host_callable")
    assert blender_callable in error["message"]


def test_action_engine_pins_preflight_session_for_execution(monkeypatch):
    plan = compile_dynamic_pipeline(
        "Export a static mesh from Blender into the Tech Connector engine.",
        project_root="C:/depot/tools",
    )
    calls = []

    def execute(host, operation, callable_name, params, **kwargs):
        calls.append((host, operation, kwargs.get("session_port")))
        if host == "blender":
            return {"fbx_path": params["filepath"]}
        return {"asset_id": "tc.asset.demo", "asset_count": 1}

    monkeypatch.setattr(
        "tech_connector.game_engine.integration.pipeline_operation_runtime_service.execute_pipeline_operation",
        execute,
    )
    report = ActionExecutionEngine().execute_plan(
        plan,
        ExecutionContext(
            approved=True,
            policy={"pipeline_live_preflight": "required"},
            services={
                "pipeline_preflight_bridge_factory": lambda host: _PreflightBridge(host, [7021]),
            },
        ),
    )

    assert report["status"] == "completed"
    assert calls[0] == ("blender", "io.export_fbx", 7021)
    assert calls[1][0] == "tech_connector"
    assert calls[1][2] is None


def test_pipeline_approval_names_each_host_operation_and_effect():
    plan = compile_dynamic_pipeline(
        "Export a static mesh from Blender into the Tech Connector engine.",
        project_root="C:/depot/tools",
    )

    report = ActionExecutionEngine().execute_plan(plan, ExecutionContext(approved=False))
    text = format_action_plan_chat_report(plan, report)

    assert report["status"] == "approval_required"
    assert report["approval"]["summary"].startswith("Confirmation covers 2 mutating operations")
    assert "`blender` → `io.export_fbx`" in text
    assert "`tech_connector` → `asset.import_interchange`" in text
    assert "may change the open scene or project" in text


def test_preflight_failure_chat_reports_actionable_host_reason():
    plan = compile_dynamic_pipeline(
        "Export a static mesh from Blender into the Tech Connector engine.",
        project_root="C:/depot/tools",
    )
    report = ActionExecutionEngine().execute_plan(
        plan,
        ExecutionContext(
            approved=True,
            policy={"pipeline_live_preflight": "required"},
            services={
                "pipeline_preflight_bridge_factory": lambda host: _PreflightBridge(host, []),
            },
        ),
    )

    text = format_action_plan_chat_report(plan, report)

    assert "stopped before changing anything" in text
    assert "No live blender bridge session was found" in text
