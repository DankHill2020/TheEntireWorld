from __future__ import annotations

import pytest

from tech_connector.game_engine.authoring.engine_graph_program_service import (
    EngineGraphNode,
    EngineGraphProgram,
    GraphAuthoringContext,
    GraphInputBinding,
    GraphOperationDefinition,
    attach_engine_graph_program,
    compile_engine_graph_manifest,
    engine_graph_programs_from_scene,
    find_graph_actions,
    generate_engine_graph_python,
    graph_node_controls,
    parse_engine_graph_python,
    register_graph_operation,
    unregister_graph_operation,
    available_graph_operations,
    _ordered_nodes,
)
from tech_connector.game_engine.runtime.tc_player_build_service import SUPPORTED_RUNTIME_GRAPH_OPERATIONS


def _movement_program() -> EngineGraphProgram:
    return EngineGraphProgram(
        program_id="player_movement",
        display_name="Player Movement",
        entry_event="While Playing",
        description="Move the player from the current movement input.",
        nodes=[
            EngineGraphNode(
                "read_move",
                "input.read_axis",
                "Read Movement Input",
                {"axis": GraphInputBinding(literal="Move")},
                output_name="value",
                position=(120.0, 80.0),
            ),
            EngineGraphNode(
                "calculate_move",
                "movement.calculate_velocity",
                "Calculate Movement",
                {
                    "direction": GraphInputBinding(mode="link", source_node="read_move", source_output="value"),
                    "speed": GraphInputBinding(literal=7.5),
                    "acceleration": GraphInputBinding(literal=30.0),
                },
                output_name="velocity",
                position=(420.0, 80.0),
            ),
            EngineGraphNode(
                "apply_move",
                "actor.set_velocity",
                "Set Actor Movement",
                {
                    "target": GraphInputBinding(literal="Self"),
                    "velocity": GraphInputBinding(mode="link", source_node="calculate_move", source_output="velocity"),
                },
                output_name="",
                position=(720.0, 80.0),
            ),
        ],
        flow=["read_move", "calculate_move", "apply_move"],
    )


def test_every_exposed_graph_operation_has_a_packaged_runtime_implementation() -> None:
    exposed = {row["operation"] for row in available_graph_operations()}

    assert exposed <= SUPPORTED_RUNTIME_GRAPH_OPERATIONS


def test_graph_and_python_are_reversible_views_with_stable_identity_and_layout() -> None:
    original = _movement_program()
    code = generate_engine_graph_python(original)
    parsed = parse_engine_graph_python(code, previous=original)

    assert parsed.ok and parsed.program is not None
    assert "# tc-node: calculate_move" in code
    assert [node.node_id for node in parsed.program.nodes] == ["read_move", "calculate_move", "apply_move"]
    assert parsed.program.nodes[1].position == (420.0, 80.0)
    assert parsed.program.nodes[1].inputs["direction"].source_node == "read_move"
    assert parsed.program.nodes[2].inputs["velocity"].source_node == "calculate_move"


def test_code_edit_updates_the_graph_literal_without_rebuilding_the_graph_asset() -> None:
    original = _movement_program()
    code = generate_engine_graph_python(original).replace("speed=7.5", "speed=12.0")
    parsed = parse_engine_graph_python(code, previous=original)

    assert parsed.ok and parsed.program is not None
    calculate = next(node for node in parsed.program.nodes if node.node_id == "calculate_move")
    assert calculate.inputs["speed"].literal == 12.0
    assert calculate.position == (420.0, 80.0)


def test_graph_properties_are_friendly_described_and_keep_technical_keys_internal() -> None:
    node = _movement_program().nodes[1]
    controls = graph_node_controls(node)
    by_key = {row["key"]: row for row in controls}

    assert by_key["speed"]["display_name"] == "Movement Speed"
    assert by_key["speed"]["units"] == "m/s"
    assert "normal conditions" in by_key["speed"]["description"]
    assert by_key["direction"]["connected"]
    assert by_key["direction"]["connection"] == "read_move.value"


def test_generated_code_executes_through_the_same_operation_boundary() -> None:
    applied: list[tuple[str, tuple[float, float, float]]] = []
    context = {
        "graph_operations": {
            "input.read_axis": lambda **_: (1.0, 0.0),
            "movement.calculate_velocity": lambda direction, speed, **_: (direction[0] * speed, 0.0, direction[1] * speed),
            "actor.set_velocity": lambda target, velocity, **_: applied.append((target, velocity)),
        }
    }
    namespace: dict[str, object] = {}
    exec(generate_engine_graph_python(_movement_program()), namespace)
    namespace["player_movement"](context)

    assert applied == [("Self", (7.5, 0.0, 0.0))]


def test_invalid_or_unrepresentable_code_reports_a_clear_diagnostic_and_keeps_previous_graph() -> None:
    previous = _movement_program()
    syntax = parse_engine_graph_python("def player_movement(context):\n    if", previous=previous)
    unsupported = parse_engine_graph_python("def player_movement(context):\n    print('hidden side effect')", previous=previous)

    assert not syntax.ok and syntax.program is previous
    assert syntax.diagnostics[0]["code"] == "syntax_error"
    assert not unsupported.ok
    assert unsupported.diagnostics[0]["code"] == "unsupported_call"


def test_native_manifest_uses_the_same_nodes_and_versioned_c_boundary() -> None:
    manifest = compile_engine_graph_manifest(_movement_program())

    assert manifest["valid"]
    assert manifest["abi"] == "tc_graph_c_v1"
    assert manifest["execution_order"] == ["read_move", "calculate_move", "apply_move"]
    assert manifest["nodes"][1]["inputs"]["direction"]["source_node"] == "read_move"


def test_manifest_is_deterministic_for_cyclic_graphs_and_reports_the_cycle() -> None:
    cyclic = EngineGraphProgram(
        "loop",
        "Cycle Loop",
        nodes=[
            EngineGraphNode(
                "node_a",
                "input.read_axis",
                "Node A",
                {"axis": GraphInputBinding(mode="link", source_node="node_b", source_output="value")},
                output_name="value",
            ),
            EngineGraphNode(
                "node_b",
                "input.read_axis",
                "Node B",
                {"axis": GraphInputBinding(mode="link", source_node="node_a", source_output="value")},
                output_name="value",
                position=(100.0, 0.0),
            ),
        ],
        flow=["node_a", "node_b"],
    )
    manifest = compile_engine_graph_manifest(cyclic)
    codes = {item["code"] for item in manifest["diagnostics"]}
    ordered = [node.node_id for node in _ordered_nodes(cyclic)]

    assert not manifest["valid"]
    assert "data_cycle" in codes
    assert manifest["execution_order"] == []
    assert ordered == ["node_a", "node_b"]


def test_program_graph_code_and_native_manifest_round_trip_with_the_scene() -> None:
    scene = {"metadata": {}}
    entry = attach_engine_graph_program(scene, _movement_program())
    restored = engine_graph_programs_from_scene(scene)["player_movement"]

    assert entry["source_code"].startswith("# TC Graph Program: Player Movement")
    assert entry["native_manifest"]["valid"]
    assert restored.nodes[1].inputs["direction"].source_node == "read_move"
    assert restored.nodes[1].position == (420.0, 80.0)


def test_public_engine_api_exposes_the_same_graph_code_and_compile_contract() -> None:
    from tech_connector.game_engine.runtime.tc_engine_api import engine

    program = _movement_program()
    code = engine.graph_to_code(program)
    parsed = engine.code_to_graph(code, previous=program)
    manifest = engine.compile_graph(parsed.program)

    assert parsed.ok
    assert manifest["valid"]
    assert manifest["program_id"] == "player_movement"


def test_context_sensitive_actions_filter_by_graph_owner_capability_and_pin_type() -> None:
    context = GraphAuthoringContext(
        graph_kind="gameplay",
        owner_type="Character",
        selected_types=("Character",),
        available_capabilities=("input", "movement", "events"),
        requested_input_type="Vector2",
        authority="owner",
    )
    actions = find_graph_actions(context=context, context_sensitive=True)

    assert [row["operation"] for row in actions] == ["input.read_axis"]
    assert actions[0]["availability_label"] == "Available Here"


def test_global_action_search_keeps_incompatible_actions_visible_and_explains_why() -> None:
    context = GraphAuthoringContext(
        graph_kind="ui",
        owner_type="Widget",
        selected_types=("Button",),
        available_capabilities=("events",),
    )
    contextual = find_graph_actions("movement", context=context, context_sensitive=True)
    global_rows = find_graph_actions("movement", context=context, context_sensitive=False)

    assert contextual == []
    assert global_rows
    assert all(not row["available"] for row in global_rows)
    assert all(row["availability_explanation"] for row in global_rows)
    assert any("UI" in row["availability_explanation"] for row in global_rows)


def test_dragging_a_vector_output_only_offers_nodes_that_can_consume_it() -> None:
    actions = find_graph_actions(
        context=GraphAuthoringContext(
            graph_kind="gameplay",
            owner_type="Character",
            available_capabilities=("input", "movement", "events"),
            dragged_output_type="Vector2",
        ),
        context_sensitive=True,
    )

    assert [row["operation"] for row in actions] == ["movement.calculate_velocity"]


def test_authoring_validation_rejects_missing_misspelled_and_out_of_range_properties() -> None:
    program = EngineGraphProgram(
        "invalid_movement",
        "Invalid Movement",
        nodes=[
            EngineGraphNode(
                "calculate",
                "movement.calculate_velocity",
                inputs={
                    "speeed": GraphInputBinding(literal=4.0),
                    "acceleration": GraphInputBinding(literal=-1.0),
                },
            )
        ],
    )
    manifest = compile_engine_graph_manifest(program)
    codes = {row["code"] for row in manifest["diagnostics"]}

    assert not manifest["valid"]
    assert {"unknown_input", "required_input_missing", "invalid_property_value"}.issubset(codes)
    assert manifest["execution_order"] == []
    assert manifest["nodes"] == []
    assert manifest["operation_contracts"] == {}


def test_code_parser_normalizes_friendly_property_aliases_to_stable_keys() -> None:
    original = _movement_program()
    code = generate_engine_graph_python(original).replace("acceleration=30.0", "accel=30.0")
    parsed = parse_engine_graph_python(code, previous=original)
    calculate = next(node for node in parsed.program.nodes if node.node_id == "calculate_move")

    assert parsed.ok
    assert "acceleration" in calculate.inputs
    assert "accel" not in calculate.inputs


def test_authoring_operation_registry_requires_explicit_replacement() -> None:
    definition = GraphOperationDefinition(
        "test.clean_registry",
        "Clean Registry",
        "Exercise safe plug-in registration.",
        "Testing",
    )
    try:
        register_graph_operation(definition)
        with pytest.raises(KeyError, match="already registered"):
            register_graph_operation(definition)
        register_graph_operation(definition, replace=True)
    finally:
        unregister_graph_operation(definition.operation)
