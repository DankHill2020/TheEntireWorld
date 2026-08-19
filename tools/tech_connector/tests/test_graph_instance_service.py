from __future__ import annotations

import pytest

from tech_connector.game_engine.authoring.engine_graph_program_service import (
    EngineGraphNode,
    EngineGraphProgram,
    GraphInputBinding,
    compile_engine_graph_manifest,
)
from tech_connector.game_engine.runtime.graph_execution_service import GraphExecutionContext
from tech_connector.game_engine.runtime.graph_instance_service import GraphRuntimeInstance


def _tick_program(speed: float = 6.0) -> EngineGraphProgram:
    return EngineGraphProgram(
        "player_tick",
        "Player Tick",
        entry_event="While Playing",
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
                    "speed": GraphInputBinding(literal=speed),
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


def _context() -> GraphExecutionContext:
    return GraphExecutionContext(
        input_actions={"Move": (1.0, 0.0)},
        actors={"Self": {"velocity": (0.0, 0.0, 0.0)}},
    )


def test_fixed_step_tick_is_deterministic_and_bounds_catch_up_work() -> None:
    context = _context()
    runtime = GraphRuntimeInstance(
        compile_engine_graph_manifest(_tick_program()),
        context,
        fixed_step_seconds=0.1,
        max_substeps=2,
        max_frame_delta=1.0,
    )
    receipt = runtime.tick(0.35)

    assert receipt.ok
    assert receipt.steps_executed == 2
    assert receipt.simulated_seconds == pytest.approx(0.2)
    assert receipt.dropped_seconds == pytest.approx(0.1)
    assert receipt.accumulator_seconds == pytest.approx(0.05)
    assert context.actors["Self"]["velocity"] == pytest.approx((0.8, 0.0, 0.0))


def test_pause_and_resume_do_not_accumulate_hidden_simulation_time() -> None:
    context = _context()
    runtime = GraphRuntimeInstance(
        compile_engine_graph_manifest(_tick_program()),
        context,
        fixed_step_seconds=0.1,
    )
    runtime.set_paused(True)
    paused = runtime.tick(1.0)
    runtime.set_paused(False)
    resumed = runtime.tick(0.1)

    assert paused.status == "paused" and paused.steps_executed == 0
    assert resumed.steps_executed == 1
    assert context.actors["Self"]["velocity"] == pytest.approx((0.4, 0.0, 0.0))


def test_begin_play_and_named_event_graphs_only_run_for_their_event() -> None:
    program = EngineGraphProgram(
        "announce_ready",
        "Announce Ready",
        entry_event="On Begin Play",
        nodes=[
            EngineGraphNode(
                "announce",
                "event.emit",
                inputs={
                    "event": GraphInputBinding(literal="World.Ready"),
                    "payload": GraphInputBinding(literal={"source": "graph"}),
                },
                output_name="",
            )
        ],
    )
    context = GraphExecutionContext()
    runtime = GraphRuntimeInstance(compile_engine_graph_manifest(program), context)

    wrong_event = runtime.run_event("On Interact")
    first = runtime.begin_play()
    second = runtime.begin_play()

    assert wrong_event.status == "idle"
    assert first.ok
    assert second.status == "idle"
    assert context.events == [
        {
            "event": "World.Ready",
            "payload": {"source": "graph"},
            "authority": "local",
        }
    ]
    assert "current_graph_event" not in context.metadata


def test_hot_swap_preserves_runtime_state_and_rejects_incompatible_manifests() -> None:
    context = _context()
    runtime = GraphRuntimeInstance(
        compile_engine_graph_manifest(_tick_program()),
        context,
        fixed_step_seconds=0.1,
    )
    runtime.tick(0.1)
    updated = compile_engine_graph_manifest(_tick_program(speed=9.0))
    accepted = runtime.hot_swap(updated)
    invalid = dict(updated)
    invalid["abi"] = "different_abi"
    rejected = runtime.hot_swap(invalid)
    different_program = dict(updated)
    different_program["program_id"] = "other_program"
    wrong_program = runtime.hot_swap(different_program)

    assert accepted["accepted"]
    assert not rejected["accepted"]
    assert not wrong_program["accepted"]
    assert runtime.elapsed_seconds == pytest.approx(0.1)
    assert context.actors["Self"]["velocity"] == pytest.approx((0.4, 0.0, 0.0))


def test_public_api_creates_a_stateful_graph_runtime() -> None:
    from tech_connector.game_engine.runtime.tc_engine_api import engine

    context = _context()
    runtime = engine.create_graph_runtime(
        _tick_program(),
        context,
        fixed_step_seconds=0.2,
    )

    assert runtime.tick(0.2).ok
    assert context.actors["Self"]["velocity"] == pytest.approx((0.8, 0.0, 0.0))


def test_mapping_context_synchronizes_live_input_and_committed_actor_state() -> None:
    context = {
        "input_actions": {"Move": (1.0, 0.0)},
        "actors": {"Self": {"velocity": (0.0, 0.0, 0.0)}},
    }
    runtime = GraphRuntimeInstance(
        compile_engine_graph_manifest(_tick_program()),
        context,
        fixed_step_seconds=0.1,
    )
    runtime.tick(0.1)
    context["input_actions"]["Move"] = (0.0, 1.0)
    runtime.tick(0.1)

    assert context["actors"] == runtime.context.actors
    assert context["actors"]["Self"]["velocity"][2] > 0.0


def test_runtime_owns_a_defensive_copy_of_the_manifest() -> None:
    manifest = compile_engine_graph_manifest(_tick_program())
    runtime = GraphRuntimeInstance(manifest, _context())
    manifest["entry_event"] = "On Begin Play"
    manifest["nodes"].clear()

    assert runtime.entry_event == "While Playing"
    assert len(runtime.manifest["nodes"]) == 3
