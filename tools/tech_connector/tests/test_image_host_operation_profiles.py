from __future__ import annotations

import json

from tech_connector.bridges.gimp.gimp_bridge import GimpBridge, PLUGIN_SOURCE_CODE as GIMP_PLUGIN_SOURCE
from tech_connector.bridges.photoshop.photoshop_bridge import PhotoshopBridge, PLUGIN_JS_SOURCE
from tech_connector.game_engine.integration.dcc_capability_audit_service import audit_dcc_host
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation


def test_image_hosts_have_scoped_concrete_operation_profiles() -> None:
    compile(GIMP_PLUGIN_SOURCE, "<gimp-plugin>", "exec")
    assert 'command === "batch_play"' in PLUGIN_JS_SOURCE
    assert "file_path: filePath" in PLUGIN_JS_SOURCE
    assert '"dimensions and bit depth"' in PLUGIN_JS_SOURCE
    assert '"color profile"' in PLUGIN_JS_SOURCE

    photoshop = audit_dcc_host("photoshop")
    gimp = audit_dcc_host("gimp")
    assert photoshop.status == "translated" and photoshop.executable_operation_count == 6
    assert gimp.status == "translated" and gimp.executable_operation_count == 3
    assert dcc_operation_registry("photoshop")["document.batch_play"].mutates_project
    assert dcc_operation_registry("gimp")["texture.pack_pbr"].mutates_project


def test_pipeline_runtime_dispatches_photoshop_and_gimp_commands(monkeypatch) -> None:
    photoshop_calls = []
    gimp_calls = []
    monkeypatch.setattr(
        PhotoshopBridge,
        "execute_command",
        lambda self, command, params=None: (True, json.dumps({"command": command, "params": params or {}})),
    )
    monkeypatch.setattr(
        GimpBridge,
        "execute_command",
        lambda self, command, params: (True, json.dumps({"command": command, "params": params})),
    )

    photoshop = execute_pipeline_operation(
        "photoshop",
        "document.batch_play",
        "photoshop.command.batch_play",
        {"descriptor": {"_obj": "select"}},
    )
    gimp = execute_pipeline_operation(
        "gimp",
        "image.convert_batch",
        "gimp.command.convert_image_format_batch",
        {"files": ["a.png"], "target_format": "tga"},
    )

    assert photoshop["command"] == "batch_play"
    assert photoshop["params"]["descriptor"]["_obj"] == "select"
    assert gimp["command"] == "convert_image_format_batch"
    assert gimp["params"]["files"] == ["a.png"]


def test_photoshop_document_snapshot_is_exact_session_metadata(monkeypatch) -> None:
    calls = []

    def execute_on_port(self, payload, *, port, timeout=10):
        calls.append((json.loads(payload)["command"], port, timeout))
        if calls[-1][0] == "document.info":
            return True, json.dumps({
                "name": "hero.psd", "file_path": "C:/art/hero.psd",
                "width": 2048, "height": 2048, "layerCount": 2,
            })
        return True, json.dumps(["Color", "Roughness"])

    monkeypatch.setattr(PhotoshopBridge, "execute_on_port", execute_on_port)
    ok, snapshot = PhotoshopBridge().get_scene_snapshot(port=7064, timeout=4.0)

    assert ok and snapshot["provider_id"] == "photoshop"
    assert snapshot["scene"] == "C:/art/hero.psd"
    assert [item["name"] for item in snapshot["objects"]] == ["Color", "Roughness"]
    assert calls == [("document.info", 7064, 4.0), ("layer.list", 7064, 4.0)]


def test_gimp_document_snapshot_is_exact_session_metadata(monkeypatch) -> None:
    calls = []
    payload = {
        "schema": "tech_connector.gimp.document_snapshot.v1",
        "provider_id": "gimp",
        "scene": "C:/art/orm.xcf",
        "objects": [{"native_id": "layer:0:ORM", "name": "ORM", "type": "image_layer"}],
    }

    def execute_python_fu(self, code, host="127.0.0.1", port=None):
        calls.append((code, port))
        return {"ok": True, "result": json.dumps(payload)}

    monkeypatch.setattr(GimpBridge, "execute_python_fu", execute_python_fu)
    ok, snapshot = GimpBridge().get_scene_snapshot(port=7086)

    assert ok and snapshot["provider_id"] == "gimp"
    assert snapshot["objects"][0]["name"] == "ORM"
    assert calls[0][1] == 7086
    assert "gimp.image_list()" in calls[0][0]
