from bridges.substance_painter_bridge import SubstancePainterBridge
from router.command_router import CommandRouter


class FakeSubstancePainterBridge:
    def __init__(self):
        self.executed = []
        self.called = []

    def parse_input(self, text):
        return SubstancePainterBridge().parse_input(text)

    def execute(self, code, timeout=10):
        self.executed.append((code, timeout))
        return True, "executed"

    def call_function(self, function_path, args=None, kwargs=None):
        self.called.append((function_path, args or [], kwargs or {}))
        return True, "called"

    def get_current_file_code(self):
        return "print('project')"

    def get_project_status_code(self):
        return "print('status')"

    def get_scene_objects_code(self):
        return "print('texture_sets')"


def test_substance_painter_bridge_metadata():
    bridge = SubstancePainterBridge()

    assert bridge.info.id == "substance_painter"
    assert bridge.info.default_port == 7031
    assert bridge.info.supports_direct_execute is True
    assert bridge.info.supports_mcp is False


def test_substance_painter_parse_input_raw_python():
    mode, data = SubstancePainterBridge().parse_input("import substance_painter.project as project")

    assert mode == "execute"
    assert data is None


def test_substance_painter_parse_input_function_payload():
    mode, data = SubstancePainterBridge().parse_input(
        '{"function":"substance_painter_tools.export.export_textures","args":[1],"kwargs":{"preset":"pbr"}}'
    )

    assert mode == "function"
    assert data["function"] == "substance_painter_tools.export.export_textures"
    assert data["args"] == [1]
    assert data["kwargs"] == {"preset": "pbr"}


def test_command_router_executes_substance_painter_raw_text():
    router = CommandRouter()
    fake = FakeSubstancePainterBridge()
    router.substance_painter = fake

    label, ok, result = router.execute_substance_painter_from_text("print('hi')")

    assert label == "Substance Painter Execute"
    assert ok is True
    assert result == "executed"
    assert fake.executed == [("print('hi')", 10)]


def test_command_router_executes_substance_painter_function_payload():
    router = CommandRouter()
    fake = FakeSubstancePainterBridge()
    router.substance_painter = fake

    label, ok, result = router.execute_substance_painter_from_text(
        '{"function":"substance_painter_tools.export.export_textures","args":[1],"kwargs":{"preset":"pbr"}}'
    )

    assert label == "Substance Painter Function"
    assert ok is True
    assert result == "called"
    assert fake.called == [("substance_painter_tools.export.export_textures", [1], {"preset": "pbr"})]


def test_command_router_substance_painter_preset_uses_common_verbs():
    router = CommandRouter()
    fake = FakeSubstancePainterBridge()
    router.substance_painter = fake

    label, ok, result = router.execute_substance_painter_preset("texture_sets")

    assert label == "Substance Painter Texture Sets"
    assert ok is True
    assert result == "executed"
    assert fake.executed == [("print('texture_sets')", 10)]
