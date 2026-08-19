from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.dcc_production_workflow_service import PRODUCTION_WORKFLOWS
from tech_connector.game_engine.integration.scene_snapshot_provider import houdini_scene_snapshot_code
from houdini_tools import operations, validation


class _Node:
    def __init__(self, path: str, node_type: str = "geo"):
        self._path = path
        self._type = node_type
        self._children = {}
        self._inputs = {}

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def type(self):
        return SimpleNamespace(name=lambda: self._type)

    def createNode(self, node_type, node_name=None):
        name = node_name or node_type
        value = _Node(self._path.rstrip("/") + "/" + name, node_type)
        self._children[name] = value
        _NODES[value.path()] = value
        return value

    def setInput(self, index, source, _output_index=0):
        self._inputs[int(index)] = source

    def input(self, index):
        return self._inputs.get(int(index))


_NODES: dict[str, _Node] = {}


def test_houdini_registry_uses_concrete_hou_modules_and_valid_sop_topology(monkeypatch) -> None:
    _NODES.clear()
    _NODES["/obj"] = _Node("/obj", "objnet")
    fake_hou = SimpleNamespace(node=lambda path: _NODES.get(path), selectedNodes=lambda: [])
    monkeypatch.setitem(__import__("sys").modules, "hou", fake_hou)

    source = operations.node_create("sphere", parent="/obj", name="source")
    target = operations.node_create("xform", parent="/obj", name="target")
    connection = operations.node_connect(source["node_path"], target["node_path"])

    assert connection["ok"]
    assert _NODES["/obj/target"].input(0) is _NODES["/obj/source"]
    registry = dcc_operation_registry("houdini")
    assert not any(operation.function.startswith("ai_studio.") for operation in registry.values())
    assert registry["workflow.inspect_procedural_fx"].function == "houdini_tools.validation.inspect_procedural_fx"


def test_houdini_workflow_exports_the_cooked_sop_and_reads_named_parity() -> None:
    steps = PRODUCTION_WORKFLOWS["houdini.procedural_fx"].steps

    assert [step.operation for step in steps][-2:] == ["usd.export", "workflow.inspect_procedural_fx"]
    export = steps[-2]
    assert export.params["node_path"].endswith("/tc_workflow_xform")
    inspect = steps[-1]
    assert inspect.readback and inspect.output_artifact_keys == ("absolute_path",)


def test_houdini_fx_inspector_fails_closed_per_parity_dimension(monkeypatch, tmp_path) -> None:
    source = _Node("/obj/geo/source", "sphere")
    target = _Node("/obj/geo/xform", "xform")
    target.setInput(0, source)
    target.geometry = lambda: SimpleNamespace(
        boundingBox=lambda: SimpleNamespace(minvec=lambda: (-1.0, -1.0, -1.0), maxvec=lambda: (1.0, 1.0, 1.0)),
    )
    dop = _Node("/obj/dop", "dopnet")
    nodes = {value.path(): value for value in (source, target, dop)}
    monkeypatch.setitem(__import__("sys").modules, "hou", SimpleNamespace(node=lambda path: nodes.get(path)))
    stage = SimpleNamespace(GetPseudoRoot=lambda: object())
    monkeypatch.setitem(
        __import__("sys").modules,
        "pxr",
        SimpleNamespace(Usd=SimpleNamespace(Stage=SimpleNamespace(Open=lambda _path: stage))),
    )
    usd = tmp_path / "fx.usd"
    usd.write_text("#usda 1.0", encoding="utf-8")

    result = validation.inspect_procedural_fx(
        source.path(), target.path(), dop.path(), str(usd), start_frame=1, end_frame=24,
    )

    assert result["absolute_path"] == str(usd)
    assert result["parity_checks"] == {
        "node topology": True,
        "simulation frame range": True,
        "geometry bounds": True,
        "USD composition": True,
    }


def test_houdini_snapshot_captures_primitive_materials_uvs_and_gates_cost() -> None:
    code = houdini_scene_snapshot_code(
        selected_only=True,
        include_geometry=True,
        include_materials=False,
        limit=8,
    )

    compile(code, "<houdini-snapshot>", "exec")
    assert "include_materials = False" in code
    assert 'findPrimAttrib("shop_materialpath")' in code
    assert 'findVertexAttrib("uv")' in code
    assert '"material_assignments"' in code


def test_houdini_snapshot_honors_exact_session(monkeypatch) -> None:
    calls = []

    def execute_on_port(self, code, *, port, timeout=10):
        calls.append((code, port, timeout))
        return True, '{"schema":"tech_connector.houdini.scene_snapshot.v1","objects":[]}'

    monkeypatch.setattr(HoudiniBridge, "execute_on_port", execute_on_port)
    ok, snapshot = HoudiniBridge().get_scene_snapshot(
        include_materials=False,
        port=7093,
        timeout=3.0,
    )

    assert ok and snapshot["provider_id"] == "houdini"
    assert calls[0][1:] == (7093, 3.0)
    assert "include_materials = False" in calls[0][0]
