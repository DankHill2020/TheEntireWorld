"""Render-graph scheduling, synchronization, and fallback coverage."""

from __future__ import annotations

from tech_connector.game_engine.rendering.render_graph_service import (
    RenderAccess,
    RenderPass,
    RenderResource,
    build_fx_render_graph,
    compile_render_graph,
    qualify_render_graph,
)


def test_compiler_infers_hazards_barriers_and_cross_queue_fences() -> None:
    graph = compile_render_graph(
        (
            RenderResource("particles", size_bytes=4096, transient=False, external=True),
            RenderResource("visible", size_bytes=1024),
            RenderResource("color", "texture", "rgba16f", 8192),
        ),
        (
            RenderPass("cull", "compute", (
                RenderAccess("particles"), RenderAccess("visible", "write", "unordered_access"),
            )),
            RenderPass("draw", "graphics", (
                RenderAccess("visible"), RenderAccess("color", "write", "color_target"),
            )),
        ),
    )

    assert graph.dependencies["draw"] == ("cull",)
    assert any(item.resource_id == "visible" and item.queue_transfer for item in graph.barriers)
    assert graph.queue_synchronization[0].signal_pass == "cull"
    assert graph.queue_synchronization[0].wait_pass == "draw"
    assert not graph.validate()


def test_transient_resources_alias_only_when_lifetimes_do_not_overlap() -> None:
    graph = compile_render_graph(
        (
            RenderResource("scratch_a", size_bytes=1024),
            RenderResource("scratch_b", size_bytes=2048),
            RenderResource("scratch_overlap", size_bytes=512),
        ),
        (
            RenderPass("write_a", "compute", (RenderAccess("scratch_a", "write"),)),
            RenderPass("read_a", "compute", (RenderAccess("scratch_a"),)),
            RenderPass("write_b", "compute", (RenderAccess("scratch_b", "write"),)),
            RenderPass("overlap", "compute", (
                RenderAccess("scratch_b"), RenderAccess("scratch_overlap", "write"),
            )),
        ),
    )
    allocations = {item.resource_id: item for item in graph.transient_allocations}

    assert allocations["scratch_a"].slot == allocations["scratch_b"].slot
    assert allocations["scratch_overlap"].slot != allocations["scratch_b"].slot
    assert graph.aliased_transient_bytes < graph.committed_transient_bytes


def test_fx_graph_exposes_upload_fallback_without_claiming_zero_copy() -> None:
    graph = build_fx_render_graph({
        "schema": "tech_connector.simulation_render_stream.v1",
        "count": 2000,
        "provider_id": "numpy_cpu",
        "residency": "persistent_host_soa",
        "consumer_compatible": True,
        "consumer_upload_required": True,
        "end_to_end_zero_copy": False,
        "fallback_reason": "Qt Quick 3D requires a buffer upload.",
    })
    receipt = graph.to_dict()

    assert receipt["valid"]
    assert receipt["metadata"]["upload_fallback"]
    assert not receipt["metadata"]["shared_resource_path"]
    assert receipt["passes"][0]["pass_id"] == "upload_simulation_stream"
    assert "Qt Quick 3D" in receipt["metadata"]["fallback_reason"]
    assert not qualify_render_graph(graph, require_shared_resource=True)["qualified"]


def test_fx_graph_keeps_compatible_device_stream_resident() -> None:
    graph = build_fx_render_graph({
        "schema": "tech_connector.simulation_render_stream.v1",
        "count": 500000,
        "provider_id": "cuda",
        "residency": "persistent_device",
        "consumer_compatible": True,
        "consumer_upload_required": False,
        "end_to_end_zero_copy": True,
    })
    pass_ids = [item.pass_id for item in graph.passes]
    qualification = qualify_render_graph(
        graph, require_async_compute=True, require_shared_resource=True,
    )

    assert "upload_simulation_stream" not in pass_ids
    assert pass_ids.index("cull_and_compact_particles") < pass_ids.index("transparent_particles")
    assert qualification["qualified"]
    assert qualification["queue_sync_count"] >= 2


def test_cycle_and_unknown_resource_are_reported_as_diagnostics() -> None:
    graph = compile_render_graph(
        (),
        (
            RenderPass("a", "graphics", (RenderAccess("missing"),), ("b",)),
            RenderPass("b", "graphics", (), ("a",)),
        ),
    )

    assert not graph.to_dict()["valid"]
    assert any("unknown resource" in item for item in graph.validate())
    assert any("dependency cycle" in item for item in graph.validate())
