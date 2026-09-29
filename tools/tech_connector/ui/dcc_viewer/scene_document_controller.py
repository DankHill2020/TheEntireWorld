"""Central document-mutation policy for DCC commands and direct UI edits."""

from __future__ import annotations

from typing import Any

from tech_connector.ui.dcc_viewer.scene_document_lifecycle import SceneDocumentLifecycle


READ_ONLY_COMMANDS = frozenset({
    "engine.audit_capability_maturity",
    "engine.audit_dcc_hosts",
    "engine.audit_dcc_workflows",
    "engine.qualify_dcc_host",
    "engine.qualify_dcc_source_parity",
    "engine.run_dcc_workflow",
    "engine.build_runtime_geometry_plan",
    "engine.plan_playtest",
    "gameplay.explain_visual_settings",
    "gameplay.preview_visual_plan",
    "gameplay.runtime_budget",
    "gameplay.validate_experience",
    "scene.inspect_usd_composition",
    "simulation.inspect_execution_plan",
    "simulation.renderer_stats",
    "procedural.build_transfer_manifest",
    "simulation.build_transfer_manifest",
})


def command_mutates_document(command: str) -> bool:
    """Return whether a successful local adaptive command changes saved state."""
    return str(command) not in READ_ONLY_COMMANDS


def finalize_adaptive_command(
    lifecycle: SceneDocumentLifecycle,
    command: str,
    result: dict[str, Any],
    revision_before: int,
) -> dict[str, Any]:
    """Catch mutations whose executor did not create an undo checkpoint itself."""
    if (
        bool(result.get("executed"))
        and command_mutates_document(command)
        and lifecycle.revision == int(revision_before)
    ):
        lifecycle.mark_dirty()
    return result
