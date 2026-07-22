from bridges.blender_bridge import BlenderBridge
from router.command_router import CommandRouter


class FakeBlenderBridge:
    def __init__(self):
        self.executed = []
        self.called = []

    def parse_input(self, text):
        return BlenderBridge().parse_input(text)

    def execute(self, code, timeout=10):
        self.executed.append((code, timeout))
        return True, "executed"

    def call_function(self, function_path, args=None, kwargs=None):
        self.called.append((function_path, args or [], kwargs or {}))
        return True, "called"

    def get_selection_code(self):
        return "print('selection')"

    def get_current_file_code(self):
        return "print('file')"

    def get_scene_objects_code(self):
        return "print('objects')"


def test_blender_bridge_metadata():
    bridge = BlenderBridge()

    assert bridge.info.id == "blender"
    assert bridge.info.default_port == 7021
    assert bridge.info.supports_direct_execute is True
    assert bridge.info.supports_mcp is False


def test_blender_parse_input_raw_python():
    mode, data = BlenderBridge().parse_input("import bpy\nprint(bpy.data.filepath)")

    assert mode == "execute"
    assert data is None


def test_blender_parse_input_function_payload():
    mode, data = BlenderBridge().parse_input(
        '{"function":"blender_tools.mesh.create_cube","args":[1],"kwargs":{"name":"A"}}'
    )

    assert mode == "function"
    assert data["function"] == "blender_tools.mesh.create_cube"
    assert data["args"] == [1]
    assert data["kwargs"] == {"name": "A"}


def test_command_router_executes_blender_raw_text():
    router = CommandRouter()
    fake = FakeBlenderBridge()
    router.blender = fake

    label, ok, result = router.execute_blender_from_text("print('hi')")

    assert label == "Blender Execute"
    assert ok is True
    assert result == "executed"
    assert fake.executed == [("print('hi')", 10)]


def test_command_router_executes_blender_function_payload():
    router = CommandRouter()
    fake = FakeBlenderBridge()
    router.blender = fake

    label, ok, result = router.execute_blender_from_text(
        '{"function":"blender_tools.mesh.create_cube","args":[1],"kwargs":{"name":"A"}}'
    )

    assert label == "Blender Function"
    assert ok is True
    assert result == "called"
    assert fake.called == [("blender_tools.mesh.create_cube", [1], {"name": "A"})]


def test_command_router_blender_preset_uses_common_verbs():
    router = CommandRouter()
    fake = FakeBlenderBridge()
    router.blender = fake

    label, ok, result = router.execute_blender_preset("objects")

    assert label == "Blender Scene Objects"
    assert ok is True
    assert result == "executed"
    assert fake.executed == [("print('objects')", 10)]
