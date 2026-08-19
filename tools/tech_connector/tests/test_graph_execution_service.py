from __future__ import annotations

import math
import time

import pytest

from tech_connector.game_engine.authoring.engine_graph_program_service import (
    EngineGraphNode,
    EngineGraphProgram,
    GraphInputBinding,
    compile_engine_graph_manifest,
)
from tech_connector.game_engine.runtime.graph_execution_service import (
    GraphExecutionContext,
    GraphExecutionLimits,
    GraphOperationRegistry,
    create_default_graph_operation_registry,
    execute_graph_manifest,
)


def _movement_program() -> EngineGraphProgram:
    return EngineGraphProgram(
        "runtime_movement",
        "Runtime Movement",
        nodes=[
            EngineGraphNode(
                "read_move",
                "input.read_axis",
                inputs={"axis": GraphInputBinding(literal="Move")},
                output_name="value",
            ),
            EngineGraphNode(
                "calculate_move",
                "movement.calculate_velocity",
                inputs={
                    "direction": GraphInputBinding(mode="link", source_node="read_move"),
                    "speed": GraphInputBinding(literal=6.0),
                    "acceleration": GraphInputBinding(literal=4.0),
                    "target": GraphInputBinding(literal="Self"),
                },
                output_name="velocity",
            ),
            EngineGraphNode(
                "apply_move",
                "actor.set_velocity",
                inputs={
                    "target": GraphInputBinding(literal="Self"),
                    "velocity": GraphInputBinding(mode="link", source_node="calculate_move"),
                },
                output_name="",
            ),
        ],
    )


def test_runtime_executes_real_input_acceleration_and_actor_mutation() -> None:
    context = GraphExecutionContext(
        delta_seconds=0.25,
        input_actions={"Move": (2.0, 0.0)},
        actors={"Self": {"velocity": (0.0, 0.0, 0.0)}},
    )
    receipt = execute_graph_manifest(compile_engine_graph_manifest(_movement_program()), context)

    assert receipt.ok
    assert receipt.operation_count == 3
    assert context.actors["Self"]["velocity"] == pytest.approx((1.0, 0.0, 0.0))
    assert receipt.outputs["read_move"] == (1.0, 0.0)
    assert [trace.node_id for trace in receipt.traces] == ["read_move", "calculate_move", "apply_move"]


def test_repeated_ticks_accelerate_from_the_committed_actor_velocity() -> None:
    context = GraphExecutionContext(
        delta_seconds=0.25,
        input_actions={"Move": (1.0, 0.0)},
        actors={"Self": {"velocity": (0.0, 0.0, 0.0)}},
    )
    manifest = compile_engine_graph_manifest(_movement_program())

    for _ in range(3):
        assert execute_graph_manifest(manifest, context).ok

    assert context.actors["Self"]["velocity"] == pytest.approx((3.0, 0.0, 0.0))


def test_late_failure_rolls_back_all_actor_and_event_mutations() -> None:
    program = _movement_program()
    program.nodes.append(EngineGraphNode("missing", "custom.not_installed", output_name=""))
    context = GraphExecutionContext(
        delta_seconds=0.25,
        input_actions={"Move": (1.0, 0.0)},
        actors={"Self": {"velocity": (0.0, 0.0, 0.0)}},
    )
    receipt = execute_graph_manifest(compile_engine_graph_manifest(program), context)

    assert not receipt.ok
    assert not receipt.committed
    assert receipt.error["code"] == "operation_unavailable"
    assert receipt.error["node_id"] == "missing"
    assert context.actors["Self"]["velocity"] == (0.0, 0.0, 0.0)


def test_authority_denial_is_source_mapped_and_transactional() -> None:
    context = GraphExecutionContext(
        authority="client",
        input_actions={"Move": (1.0, 0.0)},
        actors={"Self": {"velocity": (0.0, 0.0, 0.0)}},
    )
    receipt = execute_graph_manifest(compile_engine_graph_manifest(_movement_program()), context)

    assert not receipt.ok
    assert receipt.error == {
        "code": "authority_denied",
        "message": "actor.set_velocity allows local, owner, server authority, not client.",
        "node_id": "apply_move",
        "operation": "actor.set_velocity",
    }
    assert context.actors["Self"]["velocity"] == (0.0, 0.0, 0.0)


def test_cancellation_and_operation_budget_stop_before_commit() -> None:
    manifest = compile_engine_graph_manifest(_movement_program())
    context = GraphExecutionContext(
        input_actions={"Move": (1.0, 0.0)},
        actors={"Self": {"velocity": (0.0, 0.0, 0.0)}},
    )
    canceled = execute_graph_manifest(manifest, context, cancellation_check=lambda: True)
    budgeted = execute_graph_manifest(
        manifest,
        context,
        limits=GraphExecutionLimits(max_operations=2),
    )

    assert canceled.status == "canceled" and canceled.operation_count == 0
    assert budgeted.error["code"] == "operation_budget_exceeded"
    assert context.actors["Self"]["velocity"] == (0.0, 0.0, 0.0)


def test_event_budget_rolls_back_events_emitted_during_the_failed_run() -> None:
    program = EngineGraphProgram(
        "announce",
        "Announce",
        nodes=[
            EngineGraphNode(
                "announce_ready",
                "event.emit",
                inputs={
                    "event": GraphInputBinding(literal="Player.Ready"),
                    "payload": GraphInputBinding(literal={"player": 7}),
                },
                output_name="",
            )
        ],
    )
    context = GraphExecutionContext(events=[{"event": "Existing", "payload": {}}])
    receipt = execute_graph_manifest(
        compile_engine_graph_manifest(program),
        context,
        limits=GraphExecutionLimits(max_events=0),
    )

    assert receipt.error["code"] == "event_budget_exceeded"
    assert context.events == [{"event": "Existing", "payload": {}}]


def test_invalid_numeric_input_fails_cleanly_without_committing_nan() -> None:
    program = _movement_program()
    program.nodes[1].inputs["speed"] = GraphInputBinding(literal=math.nan)
    context = GraphExecutionContext(
        input_actions={"Move": (1.0, 0.0)},
        actors={"Self": {"velocity": (0.0, 0.0, 0.0)}},
    )
    receipt = execute_graph_manifest(compile_engine_graph_manifest(program), context)

    assert receipt.error["code"] == "invalid_manifest"
    assert any(
        row["code"] == "invalid_property_value" and "finite" in row["message"]
        for row in compile_engine_graph_manifest(program)["diagnostics"]
    )
    assert context.actors["Self"]["velocity"] == (0.0, 0.0, 0.0)


def test_operation_registry_rejects_accidental_replacement() -> None:
    registry = GraphOperationRegistry()
    registry.register("test.operation", lambda **_: 1)

    with pytest.raises(KeyError, match="already registered"):
        registry.register("test.operation", lambda **_: 2)

    registry.register("test.operation", lambda **_: 3, replace=True)
    assert registry.resolve("test.operation")() == 3
    assert create_default_graph_operation_registry().operation_names() == (
        "actor.set_velocity",
        "audio.play",
        "branch.greater",
        "component.get_position",
        "component.set_position",
        "entity.spawn",
        "event.emit",
        "input.read_axis",
        "movement.calculate_velocity",
        "save.write",
        "ui.set_text",
        "variable.add",
        "variable.set",
    )


def test_slow_final_operation_cannot_commit_after_exceeding_time_budget() -> None:
    program = EngineGraphProgram(
        "slow_graph",
        "Slow Graph",
        nodes=[EngineGraphNode("slow", "test.slow_mutation", output_name="result")],
    )
    registry = GraphOperationRegistry()

    def slow_mutation(*, context: GraphExecutionContext) -> str:
        context.actors["Self"]["value"] = "changed"
        time.sleep(0.01)
        return "done"

    registry.register("test.slow_mutation", slow_mutation)
    context = GraphExecutionContext(actors={"Self": {"value": "original"}})
    receipt = execute_graph_manifest(
        compile_engine_graph_manifest(program),
        context,
        registry=registry,
        limits=GraphExecutionLimits(max_elapsed_ms=1.0),
    )

    assert receipt.error["code"] == "time_budget_exceeded"
    assert not receipt.committed
    assert context.actors["Self"]["value"] == "original"


def test_public_engine_api_compiles_and_executes_graph_programs() -> None:
    from tech_connector.game_engine.runtime.tc_engine_api import engine

    context = {
        "delta_seconds": 0.5,
        "input_actions": {"Move": (0.0, 1.0)},
        "actors": {"Self": {"velocity": (0.0, 0.0, 0.0)}},
    }
    receipt = engine.execute_graph(_movement_program(), context)

    assert receipt.ok
    assert context["actors"]["Self"]["velocity"] == pytest.approx((0.0, 0.0, 2.0))
