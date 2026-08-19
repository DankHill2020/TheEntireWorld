import json
import sys
from types import ModuleType, SimpleNamespace

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.engine.request_context import RequestContext
from tech_connector.game_engine.integration.dcc_execution_service import (
    DccExecutionRequest,
    UnrealExecutionAdapter,
)
from unreal_tools import blueprint as blueprint_ops
from tech_connector.game_engine.integration.scene_snapshot_provider import unreal_scene_snapshot_code


def test_unreal_snapshot_captures_all_material_slots_and_texture_dependencies() -> None:
    code = unreal_scene_snapshot_code(selected_only=True, include_materials=False, limit=9)

    compile(code, "<unreal-snapshot>", "exec")
    assert "include_materials = False" in code
    assert "component.get_num_materials()" in code
    assert "get_texture_parameter_value" in code
    assert '"material_assignments"' in code
    assert '"host_asset_path"' in code


def test_unreal_snapshot_uses_forced_endpoint_and_parses_payload(monkeypatch) -> None:
    calls = []

    def execute_python(self, source, timeout=30.0, reset_globals=False):
        calls.append((self._forced_port, source, timeout, reset_globals))
        payload = {"schema": "tech_connector.unreal.scene_snapshot.v1", "objects": []}
        return {"ok": True, "result": payload, "data": payload}

    monkeypatch.setattr(UnrealBridge, "execute_python", execute_python)
    bridge = UnrealBridge(forced_port=12359)
    ok, snapshot = bridge.get_scene_snapshot(include_materials=False, timeout=4.0)

    assert ok and snapshot["provider_id"] == "unreal"
    assert calls[0][0] == 12359
    assert calls[0][2:] == (4.0, True)
    assert "include_materials = False" in calls[0][1]


def test_unreal_snapshot_can_override_endpoint_per_call(monkeypatch) -> None:
    calls = []

    def execute_python(self, source, timeout=30.0, reset_globals=False):
        calls.append(self._forced_port)
        payload = {"schema": "tech_connector.unreal.scene_snapshot.v1", "objects": []}
        return {"ok": True, "result": payload}

    monkeypatch.setattr(UnrealBridge, "execute_python", execute_python)
    ok, _snapshot = UnrealBridge(forced_port=12359).get_scene_snapshot(port=12361)

    assert ok
    assert calls == [12361]


class _FakeClass:
    def __init__(self, path):
        self.path = path

    def get_path_name(self):
        return self.path


class _FakePinType:
    def __init__(self, name):
        self.name = name
        self.container_type = None

    def set_editor_property(self, name, value):
        setattr(self, name, value)

    def get_editor_property(self, name):
        if name == "pin_category":
            return self.name
        raise AttributeError(name)


class _FakeDefaultObject:
    def __init__(self, blueprint):
        self.blueprint = blueprint

    def get_editor_property(self, name):
        return self.blueprint.variables[name]["value"]


class _FakeBlueprint:
    def __init__(self):
        self.variables = {}
        self.components = []

    def generated_class(self):
        return self

    def get_editor_property(self, name):
        if name == "status":
            return "BS_UpToDate"
        raise AttributeError(name)


class _FakeGraph:
    def __init__(self, blueprint):
        self.blueprint = blueprint

    def add_member_variable(self, name, pin_type, default_text):
        if name in self.blueprint.variables:
            return False
        if default_text == "true":
            value = True
        elif default_text == "false":
            value = False
        elif pin_type.container_type == "array":
            value = []
        elif pin_type.name in {"int", "integer"}:
            value = int(default_text or 0)
        elif pin_type.name in {"float", "real"}:
            value = float(default_text or 0.0)
        else:
            value = default_text
        self.blueprint.variables[name] = {"type": pin_type, "value": value}
        return True


class _FakeComponent:
    def __init__(self, component_class, name=""):
        self.component_class = component_class
        self.name = name
        self.properties = {}

    def get_class(self):
        return self.component_class

    def get_path_name(self):
        return "/Game/Test.BP_Test:" + self.name

    def has_editor_property(self, name):
        return name in self.properties

    def set_editor_property(self, name, value):
        self.properties[name] = value

    def get_editor_property(self, name):
        return self.properties[name]


class _FakeSubobjectSubsystem:
    def __init__(self, blueprint):
        self.blueprint = blueprint
        self.pending = None

    def k2_gather_subobject_data_for_blueprint(self, _blueprint):
        return ["root", *range(len(self.blueprint.components))]

    def add_new_subobject(self, params):
        component = _FakeComponent(params.values["new_class"])
        self.blueprint.components.append(component)
        return len(self.blueprint.components) - 1, ""

    def rename_subobject(self, handle, name):
        self.blueprint.components[handle].name = name
        return True


class _FakeSubobjectLibrary:
    def __init__(self, blueprint):
        self.blueprint = blueprint

    @staticmethod
    def is_handle_valid(handle):
        return isinstance(handle, int) and handle >= 0

    @staticmethod
    def get_data(handle):
        return handle

    @staticmethod
    def is_component(data):
        return isinstance(data, int)

    def get_object_for_blueprint(self, data, _blueprint):
        return self.blueprint.components[data]

    def get_variable_name(self, data):
        return self.blueprint.components[data].name

    def get_display_name(self, data):
        return self.blueprint.components[data].name


class _FakeAddNewSubobjectParams:
    def __init__(self):
        self.values = {}

    def set_editor_property(self, name, value):
        self.values[name] = value


def _fake_unreal(blueprint):
    module = ModuleType("unreal")
    graph = _FakeGraph(blueprint)
    subsystem = _FakeSubobjectSubsystem(blueprint)
    module.SubobjectDataSubsystem = object()
    module.SubobjectDataBlueprintFunctionLibrary = _FakeSubobjectLibrary(blueprint)
    module.AddNewSubobjectParams = _FakeAddNewSubobjectParams
    module.PinContainerType = SimpleNamespace(ARRAY="array")
    module.EditorAssetLibrary = SimpleNamespace(
        load_asset=lambda _path: blueprint,
        save_loaded_asset=lambda _asset, _only_if_dirty: True,
    )
    module.BlueprintGraphEditor = SimpleNamespace(
        get_graph_editor_by_name=lambda _asset, _name: graph,
    )
    module.BlueprintEditorLibrary = SimpleNamespace(
        compile_blueprint=lambda _asset: True,
        list_graph_names=lambda _asset: ["EventGraph"],
        list_member_variable_names=lambda asset: list(asset.variables),
        get_basic_type_by_name=lambda name: _FakePinType(str(name)),
        get_member_variable_type=lambda asset, name: asset.variables[str(name)]["type"],
        get_blueprint_variable_category=lambda _asset, _name: "Default",
    )
    module.get_default_object = lambda asset: _FakeDefaultObject(asset)
    module.get_engine_subsystem = lambda _kind: subsystem
    component_class = _FakeClass("/Script/Engine.StaticMeshComponent")
    module.load_class = lambda _outer, path: component_class if str(path).endswith("StaticMeshComponent") else None
    return module


def test_create_variable_uses_typed_graph_api_and_default_object_readback(monkeypatch):
    asset = _FakeBlueprint()
    monkeypatch.setitem(sys.modules, "unreal", _fake_unreal(asset))

    result = json.loads(blueprint_ops.create_variable(
        "/Game/Test/BP_Test",
        "MovementSpeed",
        "float",
        default_value=420.0,
    ))

    assert result["ok"]
    assert result["variable"] == {"name": "MovementSpeed", "type": "float", "category": "Default"}
    assert result["default_value"] == 420.0
    assert all(result["postconditions"].values())


def test_create_array_variable_sets_container_type(monkeypatch):
    asset = _FakeBlueprint()
    monkeypatch.setitem(sys.modules, "unreal", _fake_unreal(asset))

    result = json.loads(blueprint_ops.create_variable(
        "/Game/Test/BP_Test",
        "Targets",
        "object",
        is_array=True,
    ))

    assert result["ok"]
    assert asset.variables["Targets"]["type"].container_type == "array"
    assert result["is_array"] is True


def test_add_component_verifies_subobject_class_after_compile_and_save(monkeypatch):
    asset = _FakeBlueprint()
    monkeypatch.setitem(sys.modules, "unreal", _fake_unreal(asset))

    result = json.loads(blueprint_ops.add_component(
        "/Game/Test/BP_Test",
        "/Script/Engine.StaticMeshComponent",
        "PreviewMesh",
    ))

    assert result["ok"]
    assert result["created"] is True
    assert result["component"]["variable_name"] == "PreviewMesh"
    assert result["component"]["class_path"] == "/Script/Engine.StaticMeshComponent"
    assert all(result["postconditions"].values())


def test_editor_only_blueprint_action_returns_actionable_delegation_without_calling_bridge():
    request = DccExecutionRequest(
        execution_environment="unreal",
        operation_mode="execute",
        target_type="operation",
        target_identifier="blueprint.open_graph",
        mutation_scope="editor_ui",
        approved=True,
        keyword_args={"blueprint_path": "/Game/Test/BP_Test", "graph_name": "EventGraph"},
    )

    result = UnrealExecutionAdapter("unreal").execute(
        request,
        RequestContext(text="Open EventGraph in BP_Test"),
    )

    assert result.status == "blocked"
    assert result.structured_data["execution_mode"] == "user_delegated"
    assert result.structured_data["delegation"]["surface"]
    assert "Surface:" in result.rendered_output
