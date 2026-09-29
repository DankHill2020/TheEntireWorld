from __future__ import annotations

from tech_connector.game_engine.authoring.engine_graph_program_service import (
    EngineGraphNode,
    EngineGraphProgram,
    GraphInputBinding,
    compile_engine_graph_manifest,
)
from tech_connector.game_engine.runtime.graph_debugger_service import (
    GraphDebugSession,
    GraphDebugSessionManager,
)


def _program(*, include_add: bool = True) -> EngineGraphProgram:
    nodes = [EngineGraphNode(
        "set_score", "variable.set", "Set Score",
        {"name": GraphInputBinding(literal="Score"), "value": GraphInputBinding(literal=10)},
    )]
    if include_add:
        nodes.append(EngineGraphNode(
            "add_score", "variable.add", "Add Score",
            {"name": GraphInputBinding(literal="Score"), "amount": GraphInputBinding(literal=5.0)},
        ))
    return EngineGraphProgram("score_program", "Score Program", nodes=nodes, flow=[row.node_id for row in nodes])


def _context() -> dict:
    return {"authority": "local", "actors": {"Self": {}}, "metadata": {"variables": {"Score": 0}}}


def test_debug_session_breakpoint_step_watches_and_state_rollback() -> None:
    external_context = _context()
    session = GraphDebugSession("debug-1", "Player_1", compile_engine_graph_manifest(_program()), external_context)
    session.set_breakpoints(["add_score"])
    session.set_watches(["metadata.variables.Score", "outputs.set_score"])

    paused = session.start()
    assert paused.status == "paused"
    assert paused.pause_reason == "breakpoint"
    assert paused.next_node_id == "add_score"
    assert paused.watches["metadata.variables.Score"] == 10
    assert paused.watches["outputs.set_score"] == 10

    complete = session.step()
    assert complete.status == "complete"
    assert complete.runtime_state["metadata"]["variables"]["Score"] == 15.0
    assert external_context["metadata"]["variables"]["Score"] == 15.0
    assert [row.node_id for row in complete.traces] == ["set_score", "add_score"]

    stopped = session.stop(keep_changes=False)
    assert stopped.runtime_state["metadata"]["variables"]["Score"] == 0
    assert external_context["metadata"]["variables"]["Score"] == 0


def test_debug_session_hot_swap_preserves_instance_state_and_position() -> None:
    session = GraphDebugSession("debug-2", "Enemy_7", compile_engine_graph_manifest(_program(include_add=False)), _context())
    session.set_breakpoints(["set_score"])
    assert session.start().status == "paused"
    assert session.step().status == "complete"

    updated = compile_engine_graph_manifest(_program(include_add=True))
    swapped = session.hot_swap(updated)
    assert swapped.status == "paused"
    assert swapped.pause_reason == "hot_swap"
    assert swapped.next_node_id == "add_score"
    assert swapped.runtime_state["metadata"]["variables"]["Score"] == 10
    assert session.continue_execution().runtime_state["metadata"]["variables"]["Score"] == 15.0


def test_debug_session_manager_lists_and_detaches_instances() -> None:
    manager = GraphDebugSessionManager()
    session = manager.attach("session-a", "Player_1", compile_engine_graph_manifest(_program()), _context())
    session.pause()

    rows = manager.list_sessions()
    assert rows[0]["instance_id"] == "Player_1"
    assert manager.session("session-a") is session
    assert manager.detach("session-a").status == "stopped"
