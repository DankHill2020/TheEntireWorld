from __future__ import annotations

from pathlib import Path

import pytest

from tech_connector.game_engine.integration import dcc_production_workflow_service as workflow_service
from tech_connector.game_engine.integration.dcc_production_workflow_service import (
    PRODUCTION_WORKFLOWS,
    WORKFLOW_LEDGER_SCHEMA,
    attach_workflow_receipt_to_scene,
    execute_dcc_workflow,
    plan_dcc_workflow,
    store_workflow_receipt,
    validate_workflow_catalog,
    validate_workflow_receipt,
    workflow_receipt_ledger,
)
from tech_connector.game_engine.scene.federated_scene_service import (
    FederatedSceneDocument,
    load_federated_scene,
    save_federated_scene,
)


def test_catalog_has_one_role_specific_restorable_workflow_per_external_host() -> None:
    audit = validate_workflow_catalog()

    assert audit["valid"]
    assert audit["workflow_count"] == 10
    assert audit["host_count"] == 10
    assert all(count >= 1 for count in audit["workflows_by_host"].values())
    assert audit["delegated_steps"] == {"substance_painter.texture_set": ["material.apply"]}
    motionbuilder = PRODUCTION_WORKFLOWS["motionbuilder.retarget_plot"]
    assert [step.operation for step in motionbuilder.steps] == [
        "io.import_fbx", "character.create_character", "character.plot_animation", "io.export_fbx", "character.inspect",
    ]
    assert not any("rig.create" in step.operation for step in motionbuilder.steps)


def test_workflow_plan_resolves_workspace_and_pins_selected_session(tmp_path) -> None:
    plan = plan_dcc_workflow(
        "3dsmax.modifier_asset",
        workspace=tmp_path,
        session_port=7094,
        step_inputs={"mesh.create_box": {"name": "HeroProp"}},
    )

    assert plan["valid"]
    assert plan["session_port"] == 7094
    assert plan["steps"][0]["params"]["name"] == "HeroProp"
    export = next(row for row in plan["steps"] if row["operation"] == "io.export")
    assert export["params"]["filepath"] == str((tmp_path / "max_asset.fbx").resolve())
    assert plan["restoration_requirements"]
    assert plan["parity_checks"]


def test_mutating_workflow_requires_explicit_confirmation(tmp_path) -> None:
    with pytest.raises(PermissionError, match="explicit confirmation"):
        execute_dcc_workflow(
            "photoshop.layered_texture",
            workspace=tmp_path,
            session_port=7061,
            executor=lambda *_args: {"ok": True},
        )


def test_all_ten_workflows_execute_in_order_on_one_pinned_session(tmp_path) -> None:
    for index, (key, workflow) in enumerate(PRODUCTION_WORKFLOWS.items()):
        calls = []
        port = 7200 + index

        def executor(host, operation, callable_name, params, session_port):
            calls.append((host, operation, callable_name, params, session_port))
            if operation in {"animation.export", "io.export_fbx", "io.export", "usd.export", "textures.export", "texture.pack_pbr"}:
                for name in ("export_path", "filepath", "output_path"):
                    if not params.get(name):
                        continue
                    path = Path(params[name])
                    if path.suffix:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(operation, encoding="utf-8")
                    else:
                        path.mkdir(parents=True, exist_ok=True)
            result = {
                "ok": True,
                "operation": operation,
                "readback": True,
                "parity_checks": {check: True for check in workflow.parity_checks},
            }
            step = workflow.steps[len(calls) - 1]
            for output_key in step.output_artifact_keys:
                artifact = tmp_path / workflow.host / "unity_outputs" / f"{operation.replace('.', '_')}.asset"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text(operation, encoding="utf-8")
                result[output_key] = str(artifact)
            return result

        receipt = execute_dcc_workflow(
            key,
            workspace=tmp_path / workflow.host,
            session_port=port,
            confirm_mutating=True,
            delegated_step_receipts={
                step.operation: {"confirmed": True, "confirmed_by": "test"}
                for step in workflow.steps
                if getattr(
                    workflow_service.dcc_operation_registry(workflow.host)[step.operation],
                    "execution_mode",
                    "host_native",
                ) == "user_delegated"
            },
            executor=executor,
        )

        assert receipt.status == "verified", key
        assert receipt.readback_complete
        assert receipt.artifact_readback_complete
        assert receipt.parity_readback_complete
        assert [call[1] for call in calls] == [
            step.operation for step in workflow.steps
            if getattr(
                workflow_service.dcc_operation_registry(workflow.host)[step.operation],
                "execution_mode",
                "host_native",
            ) != "user_delegated"
        ]
        assert [step["operation"] for step in receipt.steps] == [step.operation for step in workflow.steps]
        assert all(call[0] == workflow.host and call[4] == port for call in calls)
        assert receipt.artifacts or workflow.host in {"photoshop", "unreal"}


def test_unity_workflow_chains_real_scene_steps_and_output_artifact_readback(tmp_path) -> None:
    workflow = PRODUCTION_WORKFLOWS["unity.prefab_asset"]
    operations = [step.operation for step in workflow.steps]

    assert operations == [
        "assets.import_fbx", "material.create", "material.assign", "prefab.create",
        "scene.add_prefab", "workflow.inspect_prefab_asset",
    ]
    assert workflow.steps[-1].readback
    assert workflow.steps[-1].params["instance_name"] == "TC_WorkflowInstance"
    assert {key for step in workflow.steps for key in step.output_artifact_keys} == {"absolute_path"}


def test_unity_workflow_rejects_host_reported_artifacts_that_do_not_exist(tmp_path) -> None:
    workflow = PRODUCTION_WORKFLOWS["unity.prefab_asset"]

    def executor(_host, operation, _callable, _params, _session_port):
        step = next(item for item in workflow.steps if item.operation == operation)
        result = {
            "ok": True,
            "parity_checks": {check: True for check in workflow.parity_checks},
        }
        for key in step.output_artifact_keys:
            result[key] = str(tmp_path / "UnityProject" / "Assets" / f"missing_{operation}.asset")
        return result

    receipt = execute_dcc_workflow(
        "unity.prefab_asset",
        workspace=tmp_path,
        session_port=7047,
        confirm_mutating=True,
        executor=executor,
    )

    assert receipt.status == "failed"
    assert not receipt.artifact_readback_complete
    assert "artifact_readback" in receipt.missing_gates
    assert any("returned artifact does not exist" in error for error in receipt.errors)


def test_workflow_stops_after_first_failed_step_without_retrying_mutation(tmp_path) -> None:
    calls = []

    def executor(_host, operation, _callable_name, _params, _session_port):
        calls.append(operation)
        return {"ok": operation != "character.create_character", "error": "characterization failed"}

    receipt = execute_dcc_workflow(
        "motionbuilder.retarget_plot",
        workspace=tmp_path,
        session_port=7011,
        confirm_mutating=True,
        executor=executor,
    )

    assert receipt.status == "failed"
    assert calls == ["io.import_fbx", "character.create_character"]
    assert len(receipt.errors) == 1


def test_session_resolution_refuses_to_guess_between_multiple_endpoints(monkeypatch) -> None:
    class Bridge:
        def find_ports(self):
            return [7001, 7002]

    monkeypatch.setattr(workflow_service, "preferred_session_port", lambda _host: None)
    monkeypatch.setattr(workflow_service, "bridge_for_host", lambda _host: Bridge())

    with pytest.raises(RuntimeError, match="select a session"):
        workflow_service.resolve_workflow_session_port("maya")
    assert workflow_service.resolve_workflow_session_port("maya", 7002) == 7002


def test_workflow_receipt_source_and_artifacts_round_trip_through_tcscene(tmp_path) -> None:
    source = tmp_path / "walk.fbx"
    source.write_text("character", encoding="utf-8")
    def executor(_host, operation, _callable, params, _session_port):
        if operation == "io.export_fbx":
            Path(params["filepath"]).write_text("plotted", encoding="utf-8")
        return {
            "ok": True,
            "operation": operation,
            "parity_checks": {
                check: True for check in PRODUCTION_WORKFLOWS["motionbuilder.retarget_plot"].parity_checks
            },
        }

    receipt = execute_dcc_workflow(
        "motionbuilder.retarget_plot",
        workspace=tmp_path,
        session_port=7011,
        confirm_mutating=True,
        executor=executor,
    )
    document = FederatedSceneDocument(name="Retarget Shot")
    first = attach_workflow_receipt_to_scene(
        document,
        receipt,
        source_path=str(source),
        session_key="motionbuilder:7011",
        executable_hint="D:/Apps/MotionBuilder/motionbuilder.exe",
    )
    second = attach_workflow_receipt_to_scene(
        document,
        receipt,
        source_path=str(source),
        session_key="motionbuilder:7018",
        executable_hint="D:/Apps/MotionBuilder/motionbuilder.exe",
    )
    scene_path = save_federated_scene(tmp_path / "retarget.tcscene", document)
    restored, _blobs = load_federated_scene(scene_path)

    assert first["source_id"] == second["source_id"]
    assert len(restored.sources) == 1
    assert restored.sources[0]["session_key"] == "motionbuilder:7018"
    assert restored.sources[0]["source_fingerprint"]["exists"]
    assert restored.sources[0]["portable_artifacts"][0]["path"].endswith("motionbuilder_plotted.fbx")
    metadata = restored.metadata["dcc_workflow_receipts"]["motionbuilder.retarget_plot"]
    assert metadata["receipt"]["status"] == "verified"
    assert metadata["restoration_requirements"]
    assert metadata["parity_checks"]


def test_workflow_receipt_integrity_and_artifact_revision_are_validated(monkeypatch, tmp_path) -> None:
    class Bridge:
        pass

    bridge = Bridge()
    monkeypatch.setattr(workflow_service, "bridge_for_host", lambda _host: bridge)

    def executor(_host, operation, _callable, params, _session_port):
        if operation == "io.export_fbx":
            Path(params["filepath"]).write_text("plotted", encoding="utf-8")
        return {
            "ok": True,
            "parity_checks": {
                check: True for check in PRODUCTION_WORKFLOWS["motionbuilder.retarget_plot"].parity_checks
            },
        }

    receipt = execute_dcc_workflow(
        "motionbuilder.retarget_plot",
        workspace=tmp_path,
        session_port=7011,
        confirm_mutating=True,
        executor=executor,
    )
    valid = validate_workflow_receipt(
        "motionbuilder.retarget_plot", receipt, bridge=bridge,
    )
    Path(receipt.artifacts[0]["path"]).write_text("changed", encoding="utf-8")
    changed = validate_workflow_receipt(
        "motionbuilder.retarget_plot", receipt, bridge=bridge,
    )
    tampered = receipt.to_dict()
    tampered["steps"][0]["ok"] = False
    invalid = validate_workflow_receipt(
        "motionbuilder.retarget_plot", tampered, bridge=bridge, check_artifacts=False,
    )

    assert valid["valid"]
    assert "artifact_revision_changed" in changed["gates"]
    assert "receipt_binding" in invalid["gates"]


def test_success_response_without_promised_export_is_not_verified(tmp_path) -> None:
    receipt = execute_dcc_workflow(
        "motionbuilder.retarget_plot",
        workspace=tmp_path,
        session_port=7011,
        confirm_mutating=True,
        executor=lambda _host, operation, *_args: {"ok": True, "operation": operation},
    )

    assert receipt.status == "failed"
    assert not receipt.artifact_readback_complete
    assert receipt.artifacts[0]["exists"] is False
    assert "expected artifact was not created" in receipt.errors[0]


def test_successful_operations_and_artifacts_remain_unverified_without_parity_evidence(tmp_path) -> None:
    def executor(_host, operation, _callable, params, _session_port):
        if operation == "io.export_fbx":
            Path(params["filepath"]).write_text("plotted", encoding="utf-8")
        return {"ok": True, "operation": operation}

    receipt = execute_dcc_workflow(
        "motionbuilder.retarget_plot",
        workspace=tmp_path,
        session_port=7011,
        confirm_mutating=True,
        executor=executor,
    )

    assert receipt.status == "completed_unverified"
    assert receipt.artifact_readback_complete
    assert not receipt.parity_readback_complete
    assert receipt.missing_gates == ("parity_readback",)


def test_verified_workflow_receipt_round_trips_through_atomic_ledger(tmp_path) -> None:
    ledger_path = tmp_path / "workflow-ledger.json"

    def executor(_host, operation, _callable, params, _session_port):
        if operation == "io.export_fbx":
            Path(params["filepath"]).write_text("plotted", encoding="utf-8")
        return {
            "ok": True,
            "parity_checks": {
                check: True for check in PRODUCTION_WORKFLOWS["motionbuilder.retarget_plot"].parity_checks
            },
        }

    receipt = execute_dcc_workflow(
        "motionbuilder.retarget_plot",
        workspace=tmp_path,
        session_port=7011,
        confirm_mutating=True,
        executor=executor,
    )
    stored = store_workflow_receipt(receipt, ledger_path)
    restored = workflow_receipt_ledger(ledger_path)

    assert stored == restored
    assert restored["schema"] == WORKFLOW_LEDGER_SCHEMA
    assert restored["summary"]["recorded_workflows"] == 1
    assert restored["summary"]["verified_workflows"] == 1
    assert restored["receipts"][receipt.workflow]["receipt_id"] == receipt.receipt_id
    assert not list(tmp_path.glob("workflow-ledger.json.*.tmp"))


def test_workflow_receipt_ledger_rejects_wrong_schema_and_unknown_workflow(tmp_path) -> None:
    ledger_path = tmp_path / "workflow-ledger.json"
    ledger_path.write_text(
        '{"schema":"unexpected","receipts":{"maya.character_asset":{"status":"verified"}}}',
        encoding="utf-8",
    )

    assert workflow_receipt_ledger(ledger_path)["receipts"] == {}
    with pytest.raises(ValueError, match="registered production workflow"):
        store_workflow_receipt({"workflow": "unknown.workflow", "status": "verified"}, ledger_path)
