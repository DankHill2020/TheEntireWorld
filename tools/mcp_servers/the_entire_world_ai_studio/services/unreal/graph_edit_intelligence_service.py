"""Expert guidance for safe Unreal graph edits.

This module is intentionally side-effect free. It turns a user request plus any
available graph context into deterministic editing guidance that existing
semantic analysis, rewrite planning, and patch preview code can carry forward.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class UnrealGraphEditIntelligence:
    framework: str = "unreal_graph_edit_intelligence_v1"
    graph_roles: list[str] = field(default_factory=list)
    graph_type_guidance: list[str] = field(default_factory=list)
    insertion_strategy: list[str] = field(default_factory=list)
    communication_strategy: list[str] = field(default_factory=list)
    preflight_checks: list[str] = field(default_factory=list)
    troubleshooting_path: list[str] = field(default_factory=list)
    repair_strategies: list[str] = field(default_factory=list)
    validation_matrix: list[str] = field(default_factory=list)
    layout_plan: list[str] = field(default_factory=list)
    confidence_notes: list[str] = field(default_factory=list)
    approval_boundaries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


GRAPH_ROLE_TAXONOMY = [
    "Entry/input handling",
    "Authority and ownership checks",
    "State guards and validation",
    "Data preparation and cached reads",
    "Core action/execution",
    "Animation, VFX, audio, or UI feedback",
    "Failure, cancellation, and recovery",
    "Debugging and instrumentation",
]


BASE_PREFLIGHT = [
    "Open the target asset and graph before mutation so the user can see the edit area.",
    "Snapshot nodes, pins, links, comments, reroutes, variables, functions, macros, components, and dependencies.",
    "Confirm the graph has not changed since planning before applying edits.",
    "Resolve every planned node, pin, variable, function, event, class, and asset path against the live editor state.",
    "Classify existing node clusters by role before choosing an insertion point.",
    "Block live apply when the insertion point, pin direction, pin type, or owning graph cannot be verified.",
]


BASE_INSERTION = [
    "Insert new logic at a named subsystem boundary instead of the middle of an unrelated execution chain.",
    "Place guards before expensive traces, state mutations, movement changes, damage, spawning, saves, or replication calls.",
    "Place response/feedback nodes after the authoritative action succeeds, unless the graph already has predictive feedback.",
    "Prefer extending a related function, macro, component, or collapsed graph when the Event Graph is already dense.",
    "Preserve existing execution order and reconnect replaced links only after validating equivalent data flow.",
]


BASE_TROUBLESHOOTING = [
    "If compile fails, resolve the first structural error before secondary warnings.",
    "If pins cannot connect, compare pin direction, category, object class, container type, and latent/action context.",
    "If the target node is stale, refresh the live graph snapshot and re-resolve by GUID, title, then nearby pins.",
    "If behavior changes unexpectedly, compare reachability before and after the patch and inspect guard conditions.",
    "If layout becomes unreadable, undo layout-only changes first before rolling back functional graph edits.",
]


BASE_REPAIR = [
    "Rebuild the operation from the current graph snapshot when any planned node or pin cannot be found.",
    "Prefer adding the missing variable/function/interface only when matching project patterns already exist.",
    "Replace brittle direct references with interfaces, dispatchers, components, tags, or subsystem calls when the ownership boundary demands it.",
    "Use the rollback token or backup asset when compile validation fails after mutation.",
    "Return to plan-only mode when confidence remains low after one refresh/re-resolve attempt.",
]


BASE_VALIDATION = [
    "Compile the modified asset and capture warnings/errors.",
    "Verify all required execution pins and data pins are connected or have deliberate defaults.",
    "Verify new paths are reachable and existing paths still reach their prior outputs.",
    "Verify no unrelated nodes, comments, variables, functions, macros, or links changed.",
    "Report exact node, pin, layout, asset, and compile changes after the edit.",
]


BASE_LAYOUT = [
    "Preserve the local graph's dominant flow direction.",
    "Reserve space before creating nodes and keep wires short enough to read.",
    "Group new nodes into intent-based comment regions or expand existing related regions.",
    "Keep execution wires visually distinct from data preparation wires.",
    "Use reroutes only to reduce crossings or preserve local style.",
]


APPROVAL_BOUNDARIES = [
    "Require approval before destructive removal, broad rewiring, asset creation, save operations, or multi-asset edits.",
    "Ask a follow-up question instead of guessing when the target asset, graph, feature boundary, or desired behavior is ambiguous.",
    "Use an Approve/Deny control for binary confirmation; do not require typed yes/no for approval-only prompts.",
]


def build_unreal_graph_edit_intelligence(
    prompt: str,
    *,
    intent_domains: list[str] | None = None,
    graph_types: list[str] | None = None,
    context: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic expert guidance for an Unreal graph edit request."""
    lower = (prompt or "").lower()
    intent_domains = list(intent_domains or ["general_gameplay"])
    graph_types = list(graph_types or ["Blueprint"])
    context = context or {}
    params = params or {}

    guidance = UnrealGraphEditIntelligence(
        graph_roles=list(GRAPH_ROLE_TAXONOMY),
        graph_type_guidance=_graph_type_guidance(graph_types),
        insertion_strategy=_unique(BASE_INSERTION + _domain_insertion_strategy(intent_domains, graph_types, lower)),
        communication_strategy=_communication_strategy(intent_domains, graph_types, lower),
        preflight_checks=_unique(BASE_PREFLIGHT + _contextual_preflight(graph_types, context, params)),
        troubleshooting_path=_unique(BASE_TROUBLESHOOTING + _domain_troubleshooting(intent_domains, graph_types)),
        repair_strategies=_unique(BASE_REPAIR + _domain_repairs(intent_domains, graph_types)),
        validation_matrix=_unique(BASE_VALIDATION + _domain_validation(intent_domains, graph_types)),
        layout_plan=_unique(BASE_LAYOUT + _layout_guidance(graph_types, lower)),
        confidence_notes=_confidence_notes(context, params),
        approval_boundaries=list(APPROVAL_BOUNDARIES),
    )
    return guidance.to_dict()


def _graph_type_guidance(graph_types: list[str]) -> list[str]:
    guidance: list[str] = []
    if "Blueprint" in graph_types:
        guidance.extend(
            [
                "Blueprint edits must preserve event ownership, latent node rules, execution flow, and component/class boundaries.",
                "Prefer a reusable Actor Component, function, interface, or dispatcher when the logic crosses actor responsibilities.",
            ]
        )
    if "Animation Blueprint" in graph_types:
        guidance.extend(
            [
                "Animation Blueprint edits must map state machines, transitions, cached poses, slots, sync groups, and notifies before mutation.",
                "Transition rule changes must preserve locomotion fallbacks and avoid breaking blend timing.",
            ]
        )
    if "Material" in graph_types:
        guidance.extend(
            [
                "Material graph edits should prefer parameters or material instances before changing a base material.",
                "Validate UVs, normals, opacity, shading model, sampler count, static switches, and instruction cost.",
            ]
        )
    if "Niagara" in graph_types:
        guidance.extend(
            [
                "Niagara edits must distinguish system, emitter, module, renderer, and user parameter ownership.",
                "Prefer user parameters for gameplay-driven values and validate bindings after module changes.",
            ]
        )
    if "Control Rig" in graph_types:
        guidance.extend(
            [
                "Control Rig edits must preserve solve direction, hierarchy, spaces, units, and initial/current transform semantics.",
                "Insert rig logic near the related control or solve stage instead of creating disconnected graph islands.",
            ]
        )
    if "Behavior Tree" in graph_types:
        guidance.append("Behavior Tree changes must preserve blackboard key contracts, decorator abort modes, and task side effects.")
    if "PCG" in graph_types:
        guidance.append("PCG graph edits must preserve spatial/data flow, seed determinism, bounds, and generation cost.")
    if "MetaSound" in graph_types:
        guidance.append("MetaSound graph edits must preserve audio-rate/control-rate expectations, triggers, and parameter contracts.")
    return guidance


def _domain_insertion_strategy(intent_domains: list[str], graph_types: list[str], lower: str) -> list[str]:
    strategy: list[str] = []
    if any(domain in intent_domains for domain in ("movement", "traversal")):
        strategy.extend(
            [
                "For traversal or movement, insert detection/eligibility before movement mode changes and animation requests.",
                "Keep collision traces, movement state, animation state, camera response, and replication boundaries separate enough to debug.",
            ]
        )
    if "combat" in intent_domains:
        strategy.append("For combat, insert validation before damage/spawn/state mutation and feedback after authoritative success.")
    if "input" in intent_domains:
        strategy.append("For input, keep input events thin and route into functions/components that own gameplay behavior.")
    if "networking" in intent_domains or any(term in lower for term in ("server", "client", "replicated", "rpc", "authority")):
        strategy.append("For networking, place authority checks before state mutation and keep client feedback distinct from server-owned state.")
    if "animation" in intent_domains or "Animation Blueprint" in graph_types:
        strategy.append("For animation, edit transition rules or anim layers at the state boundary that owns the pose decision.")
    if "effects" in intent_domains or "Niagara" in graph_types:
        strategy.append("For effects, bind gameplay data through parameters/events rather than hardcoding asset-specific constants.")
    return strategy


def _communication_strategy(intent_domains: list[str], graph_types: list[str], lower: str) -> list[str]:
    strategies = [
        "Use direct calls only inside the same clear ownership boundary.",
        "Use Blueprint Interfaces for peer actor communication where concrete classes should not be coupled.",
        "Use Event Dispatchers for one-to-many notifications owned by an actor/component.",
        "Use Actor Components for reusable feature behavior shared across actors.",
        "Use Subsystems or manager services for cross-level/project scope state.",
    ]
    if "networking" in intent_domains or "rpc" in lower or "replicated" in lower:
        strategies.extend(
            [
                "Use server RPCs only from owning clients and validate authority before authoritative state mutation.",
                "Use OnRep or explicit multicast/client notification for replicated presentation updates when appropriate.",
            ]
        )
    if "effects" in intent_domains or "Niagara" in graph_types:
        strategies.append("Use Niagara user parameters, parameter collections, or gameplay events for effect control.")
    if "animation" in intent_domains or "Animation Blueprint" in graph_types:
        strategies.append("Use animation interfaces, exposed variables, notifies, and linked anim layers instead of hard actor coupling.")
    return _unique(strategies)


def _contextual_preflight(graph_types: list[str], context: dict[str, Any], params: dict[str, Any]) -> list[str]:
    checks: list[str] = []
    if not context.get("graphs") and not context.get("nodes"):
        checks.append("Acquire a live graph snapshot before choosing final insertion points.")
    if params.get("target_asset"):
        checks.append("Verify the requested target asset path resolves in the current Unreal project.")
    if params.get("target_graph"):
        checks.append("Verify the requested graph exists and is editable in the target asset.")
    if "Animation Blueprint" in graph_types:
        checks.append("Snapshot state machines, transition rules, cached poses, slots, linked layers, and notify references.")
    if "Material" in graph_types:
        checks.append("Snapshot material inputs, parameters, static switches, texture/sample use, and material instance dependencies.")
    if "Niagara" in graph_types:
        checks.append("Snapshot system/emitter stacks, modules, user parameters, renderer bindings, and scalability settings.")
    if "Control Rig" in graph_types:
        checks.append("Snapshot hierarchy, controls, spaces, units, solve direction, and affected rig units.")
    return checks


def _domain_troubleshooting(intent_domains: list[str], graph_types: list[str]) -> list[str]:
    steps: list[str] = []
    if "networking" in intent_domains:
        steps.extend(
            [
                "For replication issues, inspect authority path, owning client, RPC direction, replicated variables, and OnRep timing.",
                "Separate server truth bugs from client presentation bugs before changing graph structure.",
            ]
        )
    if any(domain in intent_domains for domain in ("movement", "traversal")):
        steps.append("For traversal issues, verify trace hits, movement mode transitions, collision channels, root motion, camera response, and animation state.")
    if "Animation Blueprint" in graph_types:
        steps.append("For animation graph issues, inspect transition rule truth, cached pose invalidation, slot routing, sync groups, and notify timing.")
    if "Material" in graph_types:
        steps.append("For material issues, inspect parameter values, material instance overrides, static switch permutations, sampler limits, and compile errors.")
    if "Niagara" in graph_types:
        steps.append("For Niagara issues, inspect user parameter bindings, module execution order, renderer bindings, spawn/update context, and scalability culling.")
    return steps


def _domain_repairs(intent_domains: list[str], graph_types: list[str]) -> list[str]:
    repairs: list[str] = []
    if "networking" in intent_domains:
        repairs.append("Move state mutation behind the correct authority/RPC boundary instead of duplicating state on clients.")
    if "Animation Blueprint" in graph_types:
        repairs.append("Use additive transition guards or linked layers before replacing a working locomotion state path.")
    if "Material" in graph_types:
        repairs.append("Convert hardcoded material values into parameters/material instance overrides when artist tuning is likely.")
    if "Niagara" in graph_types:
        repairs.append("Expose missing gameplay-driven values as user parameters and rebind modules/renderers after structural changes.")
    if "Control Rig" in graph_types:
        repairs.append("Reinsert rig logic at the correct solve stage and preserve initial/current transform usage.")
    return repairs


def _domain_validation(intent_domains: list[str], graph_types: list[str]) -> list[str]:
    checks: list[str] = []
    if "networking" in intent_domains:
        checks.extend(["Validate server/client authority behavior.", "Validate replicated values, RPC calls, and OnRep presentation paths."])
    if any(domain in intent_domains for domain in ("movement", "traversal")):
        checks.append("Run or request a focused movement/traversal smoke test covering success, failure, cancel, and recovery cases.")
    if "Animation Blueprint" in graph_types:
        checks.append("Validate animation preview, transition rules, cached poses, slots, and notify-driven behavior.")
    if "Material" in graph_types:
        checks.append("Compile material and affected material instances; report shader warnings and parameter changes.")
    if "Niagara" in graph_types:
        checks.append("Validate Niagara system/emitter compile, parameter bindings, renderer output, and expected spawn/update behavior.")
    if "Control Rig" in graph_types:
        checks.append("Validate rig compile, solve order, control transforms, hierarchy integrity, and preview pose behavior.")
    return checks


def _layout_guidance(graph_types: list[str], lower: str) -> list[str]:
    layout: list[str] = []
    if any(term in lower for term in ("prototype", "new feature", "add")):
        layout.append("Create a compact, labeled new region near the insertion point, not at the far edge of the graph.")
    if "Animation Blueprint" in graph_types:
        layout.append("Keep state machine edits visually near the affected state/transition and avoid crossing pose wires.")
    if "Material" in graph_types:
        layout.append("Group material math by input channel and keep parameter nodes close to the math they drive.")
    if "Niagara" in graph_types:
        layout.append("Keep Niagara module edits in the correct stack context and name changed parameter bindings clearly.")
    if "Control Rig" in graph_types:
        layout.append("Align Control Rig edits by solve order and affected control/hierarchy region.")
    return layout


def _confidence_notes(context: dict[str, Any], params: dict[str, Any]) -> list[str]:
    notes = []
    if not context:
        notes.append("Confidence is limited until a live Unreal graph snapshot is captured.")
    elif not context.get("graphs") and not context.get("nodes"):
        notes.append("Context exists, but final insertion requires node/pin/link-level graph data.")
    else:
        notes.append("Use the live graph snapshot to choose and reverify insertion points before mutation.")
    if not params.get("target_asset"):
        notes.append("Target asset is unresolved; keep work in discovery/plan mode until resolved.")
    notes.append("When confidence is low, report the uncertainty and continue with non-mutating discovery or a preview-only patch.")
    return notes


def _unique(values: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
