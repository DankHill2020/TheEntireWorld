"""Semantic Unreal graph understanding before safe graph modification.

This module does not edit assets. It builds the deterministic comprehension
payload that graph-editing operations must carry before they are allowed to
create, insert, reconnect, or delete graph nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


GRAPH_TYPES = (
    "Blueprint",
    "Animation Blueprint",
    "Material",
    "Niagara",
    "Behavior Tree",
    "State Machine",
    "Control Rig",
    "PCG",
    "MetaSound",
)

BEST_PRACTICE_DOMAINS = {
    "blueprint_architecture": [
        "Prefer small functions/macros/components over expanding an already dense EventGraph.",
        "Reuse existing variables, functions, interfaces, dispatchers, and components before adding duplicates.",
        "Keep execution wiring readable with comments/regions and preserve existing reroute/comment structure.",
    ],
    "gameplay_framework": [
        "Respect Character, Controller, GameMode, GameState, PlayerState, and Component ownership boundaries.",
        "Prefer Actor Components for reusable mechanics that do not belong directly in one Blueprint class.",
        "Route cross-actor communication through interfaces, events, dispatchers, or subsystem-owned services when appropriate.",
    ],
    "enhanced_input": [
        "Use existing Input Actions and Mapping Contexts when present.",
        "Keep input handling separate from gameplay implementation when the project already has component/service boundaries.",
    ],
    "animation": [
        "Avoid breaking locomotion state machines, cached poses, layered blends, slot usage, and notify-driven behavior.",
        "Validate animation graph changes against skeleton, montage slots, motion matching or pose search data, and transition rules.",
    ],
    "control_rig": [
        "Inspect hierarchy, controls, spaces, units, and execution ordering before adding or rewiring rig nodes.",
        "Preserve solve direction, initial/current transforms, and control naming conventions.",
    ],
    "niagara": [
        "Prefer exposing user parameters over hardcoded constants when gameplay needs to drive an effect.",
        "Check emitter/system ownership, renderer bindings, module inputs, and scalability settings before structural edits.",
    ],
    "materials": [
        "Prefer material instances and parameters for tuning before editing base materials.",
        "Preserve UV, normal, opacity, and shading-model assumptions when adding nodes.",
    ],
    "replication": [
        "Identify authority, ownership, prediction, replicated variables, RPCs, and OnRep functions before modifying gameplay state.",
        "Do not add client-only graph logic for state that must be server-authoritative.",
    ],
    "performance": [
        "Avoid new Event Tick work unless the graph already owns that polling path and the cost is bounded.",
        "Prefer events, timers, state changes, cached values, and subsystem updates over per-frame scans.",
    ],
    "asset_management": [
        "Use Unreal package paths, validate referenced assets, and avoid hardcoded references if the project uses data assets/tags.",
        "Compile and validate changed Blueprints after mutation; report warnings and rollback options.",
    ],
}

INTENT_DOMAINS = {
    "movement": ("movement", "walk", "sprint", "jump", "crouch", "dash", "movementmode", "character movement"),
    "traversal": ("climb", "mantle", "ledge", "vault", "wall run", "wallrunning", "zipline", "grapple", "parkour"),
    "combat": ("combat", "damage", "weapon", "attack", "hit", "health", "death", "projectile"),
    "camera": ("camera", "spring arm", "fov", "shake", "aim", "look"),
    "animation": ("animation", "anim", "montage", "state machine", "motion matching", "pose search", "ik", "foot"),
    "input": ("input", "enhanced input", "mapping context", "input action", "keybind"),
    "networking": ("replication", "replicated", "rpc", "server", "client", "multiplayer", "prediction", "authority"),
    "ai": ("ai", "behavior tree", "blackboard", "perception", "task"),
    "effects": ("niagara", "vfx", "effect", "particle", "emitter", "sound", "metasound"),
    "materials": ("material", "shader", "texture", "parameter collection"),
    "ui": ("widget", "hud", "umg", "ui"),
    "save": ("save", "load", "checkpoint", "persistence"),
}

GRAPH_EDIT_TERMS = (
    "graph",
    "node",
    "pin",
    "blueprint",
    "anim graph",
    "event graph",
    "state machine",
    "control rig",
    "material",
    "niagara",
    "behavior tree",
    "pcg",
    "metasound",
    "connect",
    "rewire",
    "insert",
    "add",
    "modify",
    "edit",
)

VISIBLE_EDIT_STATES = [
    "REQUEST_RECEIVED",
    "CONTEXT_GATHERING",
    "GRAPH_ANALYZED",
    "CHANGE_PLANNED",
    "AWAITING_APPROVAL",
    "ASSET_OPENED",
    "TARGET_REVERIFIED",
    "EDITING",
    "LAYOUT_CLEANUP",
    "COMPILING",
    "VALIDATING",
    "SAVING",
    "REPORTING",
    "COMPLETED",
]

VISIBLE_FAILURE_STATES = [
    "BLOCKED_MISSING_CONTEXT",
    "BLOCKED_STALE_GRAPH",
    "COMPILATION_FAILED",
    "VALIDATION_FAILED",
    "ROLLED_BACK",
    "PARTIAL_COMPLETION",
    "USER_CANCELLED",
]

GRAPH_EDIT_PROGRESS_STAGES = [
    {
        "state": "REQUEST_RECEIVED",
        "message": "Graph edit request received",
        "detail": "Classifying intent, affected graph type, and risk.",
    },
    {
        "state": "CONTEXT_GATHERING",
        "message": "Gathering Unreal graph context",
        "detail": "Inspecting asset, graph, nodes, pins, variables, functions, references, and similar project patterns.",
    },
    {
        "state": "GRAPH_ANALYZED",
        "message": "Understanding graph behavior",
        "detail": "Mapping node clusters to intent, execution flow, data dependencies, and existing behavior to preserve.",
    },
    {
        "state": "CHANGE_PLANNED",
        "message": "Planning graph changes",
        "detail": "Choosing insertion points, edited nodes/pins/properties, layout strategy, validation, and rollback.",
    },
    {
        "state": "AWAITING_APPROVAL",
        "message": "Waiting for graph edit approval",
        "detail": "Showing planned changes before destructive, ambiguous, or multi-system edits.",
    },
    {
        "state": "ASSET_OPENED",
        "message": "Opening affected Unreal asset",
        "detail": "Opening the asset editor and navigating to the exact graph or section when supported.",
    },
    {
        "state": "TARGET_REVERIFIED",
        "message": "Re-verifying graph target",
        "detail": "Checking the graph still matches the plan: target nodes, pins, connections, and stale-state assumptions.",
    },
    {
        "state": "EDITING",
        "message": "Applying graph edit transaction",
        "detail": "Creating, moving, connecting, redirecting, or updating graph elements in an undoable group when supported.",
    },
    {
        "state": "LAYOUT_CLEANUP",
        "message": "Cleaning graph layout",
        "detail": "Aligning nodes, reserving space, reducing wire crossings, and applying intent-based comment regions.",
    },
    {
        "state": "COMPILING",
        "message": "Compiling modified Unreal asset",
        "detail": "Capturing compiler errors and warnings before any success report.",
    },
    {
        "state": "VALIDATING",
        "message": "Validating graph behavior and safety",
        "detail": "Checking pins, references, reachability, existing paths, layout readability, and targeted behavior.",
    },
    {
        "state": "SAVING",
        "message": "Saving validated asset changes",
        "detail": "Saving only after compile and validation thresholds are met.",
    },
    {
        "state": "REPORTING",
        "message": "Reporting graph edit results",
        "detail": "Summarizing graph diff, validation, warnings, assumptions, and undo or rollback path.",
    },
    {
        "state": "COMPLETED",
        "message": "Graph edit lifecycle complete",
        "detail": "The graph edit is complete only after visible reporting.",
    },
]

VISIBLE_EDIT_LIFECYCLE = [
    "Understand existing graph intent and dependencies before planning changes.",
    "Propose affected assets, graphs, insertion points, edited nodes/pins/properties, risks, validation, and rollback.",
    "Open and focus the affected Unreal asset or graph before mutation.",
    "Re-verify target asset, graph, nodes, pins, connections, and staleness immediately before editing.",
    "Apply graph edits in visible, atomic, undoable transactions when Unreal supports transactions.",
    "Organize graph layout as part of the edit, not as an optional cleanup.",
    "Compile changed assets, collect warnings/errors, and attempt bounded evidence-based correction if needed.",
    "Validate graph connectivity, references, layout readability, and affected behavior before saving.",
    "Report exact changes, validation performed, warnings, assumptions, and undo/rollback path.",
]

GRAPH_LAYOUT_CONTRACT = [
    "Preserve the dominant graph flow direction; prefer left-to-right when no local convention is clear.",
    "Reserve enough space before node creation to avoid overlaps, crossings, and unreadable branches.",
    "Align related nodes with consistent horizontal and vertical spacing.",
    "Group new logic into intent-based comment regions such as Input Validation, State Checks, Traversal Detection, Animation Request, Movement Execution, Replication, Failure Handling, or Debugging.",
    "Use reroute nodes intentionally to reduce wire crossings, not as clutter.",
    "Keep execution chains visually distinct from supporting data calculations.",
    "Expand existing related comment regions when appropriate instead of creating disconnected islands.",
    "Infer and preserve local graph style unless the convention is unsafe or invalid.",
    "Prefer functions, macros, collapsed graphs, or components when inline logic would become too large.",
]


@dataclass
class GraphSemanticAnalysis:
    """Structured semantic graph plan for Unreal graph work."""

    intent_domains: list[str] = field(default_factory=list)
    graph_types: list[str] = field(default_factory=list)
    affected_systems: list[str] = field(default_factory=list)
    discovery_requirements: list[str] = field(default_factory=list)
    semantic_questions: list[str] = field(default_factory=list)
    integration_strategy: list[str] = field(default_factory=list)
    preservation_checks: list[str] = field(default_factory=list)
    validation_gates: list[str] = field(default_factory=list)
    visible_edit_lifecycle: list[str] = field(default_factory=list)
    lifecycle_states: list[str] = field(default_factory=list)
    failure_states: list[str] = field(default_factory=list)
    layout_contract: list[str] = field(default_factory=list)
    pre_edit_proposal_required_fields: list[str] = field(default_factory=list)
    open_focus_operations: list[str] = field(default_factory=list)
    focus_targets: list[dict[str, str]] = field(default_factory=list)
    post_edit_report_fields: list[str] = field(default_factory=list)
    progress_stages: list[dict[str, str]] = field(default_factory=list)
    threading_contract: dict[str, Any] = field(default_factory=dict)
    edit_intelligence: dict[str, Any] = field(default_factory=dict)
    best_practice_domains: dict[str, list[str]] = field(default_factory=dict)
    required_context: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    confidence_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_domains": self.intent_domains,
            "graph_types": self.graph_types,
            "affected_systems": self.affected_systems,
            "discovery_requirements": self.discovery_requirements,
            "semantic_questions": self.semantic_questions,
            "integration_strategy": self.integration_strategy,
            "preservation_checks": self.preservation_checks,
            "validation_gates": self.validation_gates,
            "visible_edit_lifecycle": self.visible_edit_lifecycle,
            "lifecycle_states": self.lifecycle_states,
            "failure_states": self.failure_states,
            "layout_contract": self.layout_contract,
            "pre_edit_proposal_required_fields": self.pre_edit_proposal_required_fields,
            "open_focus_operations": self.open_focus_operations,
            "focus_targets": self.focus_targets,
            "post_edit_report_fields": self.post_edit_report_fields,
            "progress_stages": self.progress_stages,
            "threading_contract": self.threading_contract,
            "edit_intelligence": self.edit_intelligence,
            "best_practice_domains": self.best_practice_domains,
            "required_context": self.required_context,
            "risk_flags": self.risk_flags,
            "confidence_notes": self.confidence_notes,
        }


def is_unreal_graph_modification_request(text: str) -> bool:
    """Return whether a prompt implies structural Unreal graph work."""
    lower = (text or "").lower()
    if "unreal" not in lower and not re.search(r"\b(?:bp|abp|bpc|niagara|control rig|metasound|pcg)\b", lower):
        return False
    if re.search(
        r"\b(?:do not|don't|dont|never)\s+(?:edit|change|modify|write|save|apply|create|add|insert)\b",
        lower,
    ):
        return False
    if re.search(r"\b(?:inspect|find|identify|report|explain|analyze|analyse|plan|determine|review)\b", lower) and re.search(
        r"\b(?:do not edit|don't edit|dont edit|before making changes|before editing|not edit anything|report what you find|inspect the current project)\b",
        lower,
    ):
        return False
    return bool(
        any(term in lower for term in GRAPH_EDIT_TERMS)
        and re.search(r"\b(add|insert|edit|modify|connect|rewire|prototype|implement|create|improve|fix)\b", lower)
    )


def build_semantic_graph_analysis(
    prompt: str,
    *,
    context: dict[str, Any] | None = None,
    operation: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the semantic understanding payload for Unreal graph edits."""
    context = context or {}
    params = params or {}
    lower = (prompt or "").lower()
    intent_domains = _infer_intent_domains(lower, context)
    graph_types = _infer_graph_types(lower, context, operation, params)
    affected = _affected_systems(intent_domains)
    edit_intelligence = _build_edit_intelligence(
        prompt,
        intent_domains=intent_domains,
        graph_types=graph_types,
        context=context,
        params=params,
    )
    analysis = GraphSemanticAnalysis(
        intent_domains=intent_domains,
        graph_types=graph_types,
        affected_systems=affected,
        discovery_requirements=_discovery_requirements(graph_types),
        semantic_questions=_unique(
            _semantic_questions(intent_domains, graph_types)
            + [
                "Which graph-role cluster is the safest insertion point for this request?",
                "Which communication pattern preserves Unreal ownership boundaries for this edit?",
            ]
        ),
        integration_strategy=_unique(
            _integration_strategy(intent_domains, graph_types, operation)
            + list(edit_intelligence.get("insertion_strategy") or [])[:6]
        ),
        preservation_checks=_preservation_checks(intent_domains, graph_types),
        validation_gates=_unique(
            _validation_gates(intent_domains, graph_types)
            + list(edit_intelligence.get("validation_matrix") or [])[:8]
        ),
        visible_edit_lifecycle=list(VISIBLE_EDIT_LIFECYCLE),
        lifecycle_states=list(VISIBLE_EDIT_STATES),
        failure_states=list(VISIBLE_FAILURE_STATES),
        layout_contract=list(GRAPH_LAYOUT_CONTRACT),
        pre_edit_proposal_required_fields=_pre_edit_proposal_fields(),
        open_focus_operations=_open_focus_operations(graph_types),
        focus_targets=_focus_targets(graph_types),
        post_edit_report_fields=_post_edit_report_fields(),
        progress_stages=list(GRAPH_EDIT_PROGRESS_STAGES),
        threading_contract=graph_edit_threading_contract(),
        edit_intelligence=edit_intelligence,
        best_practice_domains=_best_practices_for(intent_domains, graph_types),
        required_context=_required_context(graph_types),
        risk_flags=_unique(
            _risk_flags(lower, intent_domains, graph_types)
            + _intelligence_risk_flags(edit_intelligence)
        ),
        confidence_notes=_unique(
            _confidence_notes(context)
            + list(edit_intelligence.get("confidence_notes") or [])
        ),
    )
    return analysis.to_dict()


def semantic_graph_report(analysis: dict[str, Any]) -> str:
    """Render a compact explanation suitable for chat or job logs."""
    if not analysis:
        return ""
    lines = ["Semantic graph understanding:"]
    for key, label in (
        ("intent_domains", "Intent domains"),
        ("graph_types", "Graph types"),
        ("affected_systems", "Affected systems"),
        ("integration_strategy", "Integration strategy"),
        ("preservation_checks", "Preservation checks"),
        ("validation_gates", "Validation gates"),
        ("visible_edit_lifecycle", "Visible lifecycle"),
        ("layout_contract", "Layout contract"),
        ("edit_intelligence", "Edit intelligence"),
        ("risk_flags", "Risk flags"),
    ):
        values = analysis.get(key) or []
        if isinstance(values, dict):
            framework = values.get("framework")
            graph_roles = values.get("graph_roles") or []
            if framework:
                lines.append(f"- {label}: {framework}; graph roles: {', '.join(str(value) for value in graph_roles[:5])}")
        elif values:
            lines.append(f"- {label}: {', '.join(str(value) for value in values[:8])}")
    return "\n".join(lines)


def graph_edit_threading_contract() -> dict[str, Any]:
    """Return the required worker/progress policy for long Unreal graph edits."""
    return {
        "background_worker_required": True,
        "separate_os_thread_per_stage": False,
        "stage_model": "sequential_state_machine_with_progress_events",
        "reason": (
            "Most Unreal graph edit stages must run in order against a consistent editor/asset state. "
            "They should run in a worker thread or command job, but each lifecycle state must emit visible progress/activity."
        ),
        "ui_requirements": [
            "Update live status label for every lifecycle state.",
            "Append visible activity entries for long-running discovery, analysis, open/focus, edit, compile, validation, and report phases.",
            "Publish remote/mobile job events for every lifecycle state.",
            "Use indeterminate progress when total work is unknown; switch to determinate counts when assets/nodes/checks are known.",
            "Keep chat responsive while work continues in background.",
            "Never hide long thinking behind silence; report the current observable task, not hidden chain-of-thought.",
        ],
        "parallelizable_stages": [
            "project pattern search",
            "reference/dependency lookup",
            "best-practice/document lookup when enabled",
            "non-mutating asset context snapshots",
        ],
        "serialized_stages": [
            "open/focus target asset",
            "target re-verification",
            "graph mutation transaction",
            "compile",
            "save",
        ],
    }


def graph_edit_progress_events() -> list[dict[str, Any]]:
    """Return determinate progress events for the visible graph edit lifecycle."""
    total = len(GRAPH_EDIT_PROGRESS_STAGES)
    events = []
    for index, stage in enumerate(GRAPH_EDIT_PROGRESS_STAGES, start=1):
        events.append(
            {
                "stage": stage["state"],
                "message": stage["message"],
                "detail": stage["detail"],
                "current": index,
                "total": total,
                "percent": int((index / total) * 100),
            }
        )
    return events


def _infer_intent_domains(lower: str, context: dict[str, Any]) -> list[str]:
    domains = []
    haystack = lower + " " + " ".join(_context_names(context)).lower()
    for domain, aliases in INTENT_DOMAINS.items():
        if any(alias in haystack for alias in aliases):
            domains.append(domain)
    return domains or ["general_gameplay"]


def _infer_graph_types(
    lower: str,
    context: dict[str, Any],
    operation: str,
    params: dict[str, Any],
) -> list[str]:
    graph_types = []
    combined = " ".join([lower, operation.lower(), " ".join(str(value).lower() for value in params.values())])
    if "anim" in combined or "state machine" in combined or "motion matching" in combined:
        graph_types.append("Animation Blueprint")
    if "control rig" in combined or "rig" in combined:
        graph_types.append("Control Rig")
    if "material" in combined or "shader" in combined:
        graph_types.append("Material")
    if "niagara" in combined or "emitter" in combined or "particle" in combined:
        graph_types.append("Niagara")
    if "behavior tree" in combined or "blackboard" in combined:
        graph_types.append("Behavior Tree")
    if "pcg" in combined:
        graph_types.append("PCG")
    if "metasound" in combined:
        graph_types.append("MetaSound")
    if "blueprint" in combined or "event graph" in combined or "bp_" in combined or "bpc_" in combined:
        graph_types.append("Blueprint")
    for graph in context.get("graphs") or []:
        name = str(graph.get("name") if isinstance(graph, dict) else graph)
        if "anim" in name.lower() and "Animation Blueprint" not in graph_types:
            graph_types.append("Animation Blueprint")
        elif name and "Blueprint" not in graph_types:
            graph_types.append("Blueprint")
    return graph_types or ["Blueprint"]


def _affected_systems(intent_domains: list[str]) -> list[str]:
    dependencies = {
        "movement": ["Input", "CharacterMovement", "Animation", "Camera", "Networking"],
        "traversal": ["Movement", "Collision", "Animation", "Camera", "Input", "Networking"],
        "combat": ["Input", "Animation", "Effects", "Damage", "Networking"],
        "camera": ["Input", "Movement", "Animation"],
        "animation": ["State Machines", "Montages", "Slots", "Skeleton", "Motion Matching"],
        "input": ["Enhanced Input", "Controller", "Pawn/Character"],
        "networking": ["Authority", "RPCs", "Replicated Variables", "Prediction"],
        "ai": ["Behavior Tree", "Blackboard", "Perception", "Navigation"],
        "effects": ["Niagara", "Materials", "Audio", "Gameplay Events"],
        "materials": ["Material Instances", "Parameters", "Asset References"],
        "ui": ["Widgets", "HUD", "Input Mode"],
        "save": ["SaveGame", "Data Assets", "Versioning"],
    }
    systems: list[str] = []
    for domain in intent_domains:
        systems.extend(dependencies.get(domain, [domain.title()]))
    return _unique(systems)


def _discovery_requirements(graph_types: list[str]) -> list[str]:
    base = [
        "graph type and owning asset",
        "nodes, pins, links, comments, reroutes, and regions",
        "variables, functions, macros, interfaces, dispatchers, components, and timelines",
        "dependencies, referencers, linked assets, data assets, gameplay tags, and cross-Blueprint calls",
    ]
    if "Animation Blueprint" in graph_types:
        base.extend(["state machines, states, transition rules, cached poses, slots, anim layers, and notify usage"])
    if "Control Rig" in graph_types:
        base.extend(["rig hierarchy, controls, spaces, solve direction, units, and execution order"])
    if "Niagara" in graph_types:
        base.extend(["emitters, modules, user parameters, renderers, bindings, and scalability settings"])
    if "Material" in graph_types:
        base.extend(["material inputs, parameters, texture references, material instances, and shading model"])
    return base


def _semantic_questions(intent_domains: list[str], graph_types: list[str]) -> list[str]:
    return [
        "What behavior does each major node cluster currently implement?",
        "Which clusters are initialization, update, validation, animation, input, networking, or output paths?",
        "Where does execution enter and leave the affected subsystem?",
        "Which data dependencies must remain stable for existing features?",
        "Which existing project pattern most closely matches the requested change?",
    ]


def _integration_strategy(intent_domains: list[str], graph_types: list[str], operation: str) -> list[str]:
    strategy = [
        "Search project for similar implementations before adding new graph structure.",
        "Prefer extending existing functions/macros/components over inserting unrelated nodes into a dense graph.",
        "Choose insertion points at subsystem boundaries, not in the middle of unrelated execution chains.",
        "Keep existing execution and data pins connected unless the plan explicitly replaces that path.",
    ]
    if "traversal" in intent_domains:
        strategy.append("Integrate traversal through movement/collision state, animation state, input, camera, and replication boundaries.")
    if "Animation Blueprint" in graph_types:
        strategy.append("Modify state machines, cached poses, slots, or transition rules only after mapping locomotion flow.")
    if operation in {"blueprint.connect_node_pins", "control_rig.connect_rig_nodes"}:
        strategy.append("Validate source/target pin types and execution direction before connecting.")
    return strategy


def _preservation_checks(intent_domains: list[str], graph_types: list[str]) -> list[str]:
    checks = [
        "existing gameplay behavior",
        "existing execution chain continuity",
        "existing data pin values and type conversions",
        "comments, regions, reroutes, and readable graph organization",
        "compile status and asset references",
    ]
    if any(domain in intent_domains for domain in ("movement", "traversal")):
        checks.extend(["movement modes", "collision traces", "camera behavior", "input bindings"])
    if "Animation Blueprint" in graph_types or "animation" in intent_domains:
        checks.extend(["state transitions", "cached poses", "montage slots", "notify-driven behavior"])
    if "networking" in intent_domains:
        checks.extend(["authority checks", "RPC ownership", "replicated variables", "prediction-sensitive paths"])
    return _unique(checks)


def _validation_gates(intent_domains: list[str], graph_types: list[str]) -> list[str]:
    gates = [
        "no orphaned graph nodes",
        "all required execution and data pins connected",
        "no invalid variable, function, asset, or interface references",
        "compile target Blueprint/assets and collect warnings/errors",
        "save only after validation or return a rollback token",
    ]
    if "performance" in intent_domains:
        gates.append("no unbounded new Event Tick work")
    if "Animation Blueprint" in graph_types:
        gates.append("animation graph/state machine validation passes")
    return gates


def _pre_edit_proposal_fields() -> list[str]:
    return [
        "modified_assets",
        "affected_graphs_functions_state_machines_or_sections",
        "existing_behavior_identified",
        "nodes_or_structures_added",
        "nodes_pins_variables_or_properties_edited",
        "nodes_or_structures_removed_or_replaced",
        "planned_insertion_points",
        "connections_created_or_redirected",
        "functionality_that_must_remain_unchanged",
        "expected_result",
        "known_risks_and_assumptions",
        "validation_steps",
        "rollback_or_recovery_plan",
    ]


def _open_focus_operations(graph_types: list[str]) -> list[str]:
    ops = [
        "navigation.open_asset",
        "blueprint.open_graph",
        "focus_or_select_planned_insertion_area_when_supported",
        "bring_unreal_editor_forward",
        "blueprint.focus_graph_item",
    ]
    if "Animation Blueprint" in graph_types:
        ops.append("animation.open_state_machine_or_anim_graph")
    if "Control Rig" in graph_types:
        ops.append("control_rig.open_rig_graph")
    if "Niagara" in graph_types:
        ops.append("niagara.open_system_or_emitter_stack")
    return ops


def _focus_targets(graph_types: list[str]) -> list[dict[str, str]]:
    targets = [
        {
            "state": "ASSET_OPENED",
            "target": "target graph",
            "purpose": "Show the user the graph area before mutation.",
        },
        {
            "state": "TARGET_REVERIFIED",
            "target": "planned insertion node, nearby node, or comment region",
            "purpose": "Confirm the exact graph item still matches the approved plan.",
        },
        {
            "state": "EDITING",
            "target": "node or connection currently being added, edited, removed, or rewired",
            "purpose": "Keep Unreal focused on the active edit item while work is happening.",
        },
        {
            "state": "VALIDATING",
            "target": "changed graph region",
            "purpose": "Return the user to the edited region for compile and validation review.",
        },
    ]
    if "Animation Blueprint" in graph_types:
        targets.append(
            {
                "state": "EDITING",
                "target": "affected state, transition rule, cached pose, slot, or anim graph node",
                "purpose": "Keep animation graph edits grounded in the exact locomotion/pose section.",
            }
        )
    if "Control Rig" in graph_types:
        targets.append(
            {
                "state": "EDITING",
                "target": "affected control, rig unit, solve stage, or hierarchy region",
                "purpose": "Keep rig edits visually aligned with solve order and hierarchy context.",
            }
        )
    if "Niagara" in graph_types:
        targets.append(
            {
                "state": "EDITING",
                "target": "affected system, emitter, module, renderer, or user parameter",
                "purpose": "Keep VFX edits visible in the stack/graph section that owns the change.",
            }
        )
    return targets


def _post_edit_report_fields() -> list[str]:
    return [
        "modified_asset",
        "modified_graph",
        "structural_graph_diff",
        "node_and_connection_changes",
        "layout_changes",
        "compile_result",
        "validation_results",
        "before_after_node_counts",
        "new_variables_functions_assets_or_dependencies",
        "pre_existing_warnings",
        "tests_performed",
        "tests_not_performed",
        "remaining_assumptions",
        "undo_or_rollback_transaction",
        "return_to_modified_section_command",
    ]


def _best_practices_for(intent_domains: list[str], graph_types: list[str]) -> dict[str, list[str]]:
    keys = {"blueprint_architecture", "asset_management", "performance"}
    if any(domain in intent_domains for domain in ("movement", "traversal", "combat", "input")):
        keys.update({"gameplay_framework", "enhanced_input"})
    if "networking" in intent_domains:
        keys.add("replication")
    if "animation" in intent_domains or "Animation Blueprint" in graph_types:
        keys.add("animation")
    if "Control Rig" in graph_types:
        keys.add("control_rig")
    if "Niagara" in graph_types or "effects" in intent_domains:
        keys.add("niagara")
    if "Material" in graph_types or "materials" in intent_domains:
        keys.add("materials")
    return {key: BEST_PRACTICE_DOMAINS[key] for key in sorted(keys)}


def _required_context(graph_types: list[str]) -> list[str]:
    context = [
        "project_index",
        "unreal_capability_graph",
        "owning_asset_context",
        "graph_node_pin_link_index",
        "similar_project_patterns",
    ]
    if "Animation Blueprint" in graph_types:
        context.append("animation_state_machine_context")
    if "Control Rig" in graph_types:
        context.append("control_rig_hierarchy_context")
    if "Niagara" in graph_types:
        context.append("niagara_system_context")
    return context


def _risk_flags(lower: str, intent_domains: list[str], graph_types: list[str]) -> list[str]:
    risks = []
    if any(term in lower for term in ("event tick", "tick", "every frame")):
        risks.append("performance_sensitive_tick_path")
    if "networking" in intent_domains:
        risks.append("network_authority_or_prediction_sensitive")
    if "Animation Blueprint" in graph_types:
        risks.append("animation_state_flow_sensitive")
    if any(term in lower for term in ("delete", "remove", "replace", "rewrite")):
        risks.append("destructive_graph_rewrite")
    if any(term in lower for term in ("connect", "rewire", "pin")):
        risks.append("pin_type_and_execution_order_sensitive")
    return risks


def _confidence_notes(context: dict[str, Any]) -> list[str]:
    notes = []
    if not context:
        notes.append("No live graph context supplied yet; require graph discovery before mutation.")
    elif not context.get("graphs") and not context.get("nodes"):
        notes.append("Asset context exists but node/pin/link-level graph data is not yet available.")
    else:
        notes.append("Use discovered graph structure before planning node insertion.")
    notes.append("If confidence remains low, optionally retrieve current Epic docs or approved references before execution.")
    return notes


def _build_edit_intelligence(
    prompt: str,
    *,
    intent_domains: list[str],
    graph_types: list[str],
    context: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    try:
        from tech_connector.services.unreal.graph_edit_intelligence_service import (
            build_unreal_graph_edit_intelligence,
        )

        return build_unreal_graph_edit_intelligence(
            prompt,
            intent_domains=intent_domains,
            graph_types=graph_types,
            context=context,
            params=params,
        )
    except Exception as exc:
        return {
            "framework": "unreal_graph_edit_intelligence_unavailable",
            "confidence_notes": [f"Graph edit intelligence unavailable: {exc}"],
        }


def _intelligence_risk_flags(edit_intelligence: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    notes = " ".join(str(item).lower() for item in (edit_intelligence.get("confidence_notes") or []))
    if "limited" in notes or "unresolved" in notes or "node/pin/link" in notes:
        risks.append("live_graph_snapshot_required_before_mutation")
    if edit_intelligence.get("approval_boundaries"):
        risks.append("approval_boundary_required_for_live_graph_edit")
    return risks


def _context_names(context: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("functions", "graphs", "variables", "components", "dependencies", "referencers"):
        for item in context.get(key) or []:
            if isinstance(item, dict):
                names.extend(str(item.get(field) or "") for field in ("name", "display_name", "path", "type"))
            else:
                names.append(str(item))
    return names


def _unique(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
