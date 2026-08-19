from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace

from substance_painter_tools.textures import export_textures
from tech_connector.bridges.substance_painter.substance_painter_bridge import SubstancePainterBridge
from tech_connector.game_engine.integration.dcc_production_workflow_service import (
    PRODUCTION_WORKFLOWS,
    execute_dcc_workflow,
)
from tech_connector.game_engine.integration.scene_snapshot_provider import substance_painter_scene_snapshot_code


def _png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + bytes(8) + int(width).to_bytes(4, "big") + int(height).to_bytes(4, "big")


def test_painter_export_uses_documented_stack_and_resource_apis(monkeypatch, tmp_path) -> None:
    stack = SimpleNamespace(__str__=lambda self: "TextureSet1/Stack1001")

    class TextureSet:
        def name(self):
            return "TextureSet1"

        def all_stacks(self):
            return [stack]

    captured = {}

    def export(config):
        captured.update(config)
        Path(config["exportPath"], "TextureSet1_BaseColor.png").write_bytes(_png_header(2048, 2048))
        return {"status": "success"}

    package = ModuleType("substance_painter")
    modules = {
        "substance_painter": package,
        "substance_painter.export": SimpleNamespace(export_project_textures=export),
        "substance_painter.project": SimpleNamespace(is_open=lambda: True),
        "substance_painter.resource": SimpleNamespace(
            ResourceID=lambda **kwargs: SimpleNamespace(url=lambda: f"resource://{kwargs['context']}/{kwargs['name']}")
        ),
        "substance_painter.textureset": SimpleNamespace(
            all_texture_sets=lambda: [TextureSet()],
            get_active_stack=lambda: stack,
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(__import__("sys").modules, name, module)

    result = export_textures(str(tmp_path / "textures"), resolution=2048)

    assert captured["exportList"] == [{"rootPath": str(stack)}]
    assert captured["defaultExportPreset"].startswith("resource://starter_assets/")
    assert result["parity_checks"] == {
        "texture-set names": True,
        "stack and UV-tile coverage": True,
        "requested channel resolution": True,
        "exported map inventory": True,
    }


def test_painter_workflow_requires_and_records_explicit_ui_delegation(tmp_path) -> None:
    workflow = PRODUCTION_WORKFLOWS["substance_painter.texture_set"]
    calls = []

    def executor(_host, operation, _callable, params, _port):
        calls.append(operation)
        if operation == "textures.export":
            target = Path(params["output_path"])
            target.mkdir(parents=True, exist_ok=True)
            (target / "basecolor.png").write_bytes(b"texture")
        return {
            "ok": True,
            "parity_checks": {check: True for check in workflow.parity_checks},
        }

    missing = execute_dcc_workflow(
        workflow.key,
        workspace=tmp_path,
        session_port=7062,
        confirm_mutating=True,
        executor=executor,
    )
    assert missing.status == "failed"
    assert calls == ["project.create"]

    calls.clear()
    receipt = execute_dcc_workflow(
        workflow.key,
        workspace=tmp_path,
        session_port=7062,
        confirm_mutating=True,
        delegated_step_receipts={
            "material.apply": {
                "confirmed": True,
                "confirmed_by": "artist@example.test",
                "evidence": {"material": "TC_WorkflowMaterial"},
            },
        },
        executor=executor,
    )

    assert receipt.status == "verified"
    assert calls == ["project.create", "textures.export"]
    delegated = next(step for step in receipt.steps if step["operation"] == "material.apply")
    assert delegated["output"]["delegated"] is True
    assert delegated["output"]["confirmed_by"] == "artist@example.test"


def test_painter_snapshot_is_lookdev_only_and_preserves_texture_set_channels() -> None:
    code = substance_painter_scene_snapshot_code(limit=7)

    compile(code, "<substance-painter-snapshot>", "exec")
    assert '"lookdev_only": True' in code
    assert '"source_shader": "substance_painter.texture_set"' in code
    assert '"texture_set_state": {"stacks": stack_rows}' in code
    assert '"include_geometry": False' in code


def test_painter_snapshot_honors_exact_session_and_parses_payload(monkeypatch) -> None:
    calls = []

    def execute_on_port(self, code, *, port, timeout=10):
        calls.append((code, port, timeout))
        return True, '{"schema":"tech_connector.substance_painter.scene_snapshot.v1","objects":[]}'

    monkeypatch.setattr(SubstancePainterBridge, "execute_on_port", execute_on_port)
    ok, snapshot = SubstancePainterBridge().get_scene_snapshot(port=7037, timeout=4.0, limit=6)

    assert ok and snapshot["provider_id"] == "substance_painter"
    assert calls[0][1:] == (7037, 4.0)
    assert "limit = max(1, min(10000, int(6)))" in calls[0][0]
