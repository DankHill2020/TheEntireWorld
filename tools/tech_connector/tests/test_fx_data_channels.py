"""Typed shared FX channels, reusable subgraphs, runtime routing, and profiling."""

from __future__ import annotations

import pytest

from tech_connector.game_engine.runtime.tc_effect_system_service import create_effect_world
from tech_connector.game_engine.runtime.tc_fx_data_channel_service import (
    FxChannelField,
    FxDataChannel,
    FxDataChannelBinding,
    FxDataChannelSchema,
    FxGraphConnection,
    FxGraphNode,
    FxGraphPort,
    FxSubgraphDefinition,
    impact_data_channel,
    publish_bound_effect_events,
)
from tech_connector.game_engine.runtime.tc_simulation_ir_service import compile_simulation_world
from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance


def test_typed_channel_validates_payload_and_uses_bounded_overflow() -> None:
    channel = FxDataChannel(FxDataChannelSchema("test", (
        FxChannelField("position", "vec3"), FxChannelField("strength", "float", 1.0),
    ), capacity=2))
    channel.publish({"position": (0, 1, 2)}, tick=1)
    channel.publish({"position": (1, 2, 3), "strength": 2}, tick=2)
    channel.publish({"position": (2, 3, 4)}, tick=3)

    assert [item.sequence for item in channel.events] == [1, 2]
    assert channel.events[-1].values["position"] == (2.0, 3.0, 4.0)
    assert channel.statistics()["dropped"] == 1
    with pytest.raises(ValueError, match="Unknown fields"):
        channel.publish({"position": (0, 0, 0), "wrong": 1}, tick=4)


def test_effect_events_publish_into_shared_impact_channel() -> None:
    world = create_effect_world("sparks", quality="low")
    system = world.effect_system
    channel = impact_data_channel(capacity=8)
    system.data_channels[channel.schema.channel_id] = channel
    system.data_channel_bindings.append(FxDataChannelBinding(
        "collision", channel.schema.channel_id, "*",
        {"position": "position", "velocity": "velocity"},
        {"normal": (0, 1, 0), "magnitude": 3.0, "surface": "metal", "source_id": "sparks"},
    ))
    system.emitted_events.append({
        "type": "collision", "emitter_id": "sparks", "position": (1, 2, 3), "velocity": (0, 4, 0),
    })

    published = publish_bound_effect_events(system, tick=7)

    assert published[0]["channel_id"] == "fx.impacts"
    assert channel.events[0].values["surface"] == "metal"
    assert channel.events[0].tick == 7


def test_subgraph_validation_catches_types_and_cycles() -> None:
    valid = FxSubgraphDefinition(
        "fx.drag", (FxGraphPort("velocity", "vec3"),), (FxGraphPort("result", "vec3"),),
        (FxGraphNode("drag", "multiply", {"value": "vec3"}, {"result": "vec3"}, {"scale": 0.9}),),
        (FxGraphConnection("$input", "velocity", "drag", "value"),
         FxGraphConnection("drag", "result", "$output", "result")),
    )
    cyclic = FxSubgraphDefinition(
        "fx.bad", nodes=(FxGraphNode("a", "copy", {"x": "float"}, {"x": "float"}),
                         FxGraphNode("b", "copy", {"x": "float"}, {"x": "float"})),
        connections=(FxGraphConnection("a", "x", "b", "x"), FxGraphConnection("b", "x", "a", "x")),
    )
    assert valid.validate() == []
    assert "dependency cycle" in cyclic.validate()[0]


def test_compiler_declares_channel_resources_and_subgraphs() -> None:
    world = create_effect_world("sparks", quality="low")
    channel = impact_data_channel()
    world.effect_system.data_channels[channel.schema.channel_id] = channel
    world.effect_system.subgraphs["fx.drag"] = FxSubgraphDefinition(
        "fx.drag", inputs=(FxGraphPort("value", "float"),), outputs=(FxGraphPort("result", "float"),),
        nodes=(FxGraphNode("copy", "copy", {"value": "float"}, {"result": "float"}),),
        connections=(FxGraphConnection("$input", "value", "copy", "value"),
                     FxGraphConnection("copy", "result", "$output", "result")),
    )
    compiled = compile_simulation_world(world, backend="reference_cpu")

    assert any(item.resource_id == "data_channel.fx.impacts" for item in compiled.resources)
    assert next(item for item in compiled.stages if item.stage_id == "data_channels").parameters["bounded"]
    assert next(item for item in compiled.stages if item.stage_id == "effects").parameters["subgraphs"] == ["fx.drag"]


def test_runtime_channel_commands_are_tick_deterministic_and_profiled() -> None:
    world = create_effect_world("sparks", quality="low")
    channel = impact_data_channel()
    world.effect_system.data_channels[channel.schema.channel_id] = channel
    runtime = SimulationRuntimeInstance(world, backend="reference_cpu")
    runtime.queue_data_channel("fx.impacts", {
        "position": (1, 2, 3), "velocity": (0, 0, 0), "normal": (0, 1, 0),
        "magnitude": 2, "surface": "stone", "source_id": "gameplay",
    }, tick=2)

    first = runtime.advance(1 / 60)
    second = runtime.advance(1 / 60)

    assert not any(item.get("type") == "data_channel" for item in first.events)
    routed = next(item for item in second.events if item.get("type") == "data_channel")
    assert routed["values"]["surface"] == "stone"
    assert second.diagnostics["execution_backend"] == "reference_cpu"
    assert not second.diagnostics["gpu_resident"]
    assert second.diagnostics["last_execution"]["elapsed_ms"] >= 0.0
    assert second.diagnostics["data_channels"]["fx.impacts"]["published"] == 1
