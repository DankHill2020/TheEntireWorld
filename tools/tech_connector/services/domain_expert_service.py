"""Modular domain expert registry for prompt understanding and advisory planning.

Experts in this module are observation/advisory capability modules. They do not
execute work or bypass existing deterministic services; they describe ownership,
context needs, safe edit patterns, and validation requirements so prompt routing
can stay more domain-aware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable


EXPERT_MODES = ("disabled", "observe", "advise", "plan", "execute")


@dataclass(frozen=True)
class DomainExpert:
    domain: str
    label: str
    application: str
    area: str
    mode: str = "observe"
    parent_domains: tuple[str, ...] = ()
    trigger_terms: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    responsibilities: tuple[str, ...] = ()
    required_context: tuple[str, ...] = ()
    safe_patterns: tuple[str, ...] = ()
    validation_steps: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    required_services: tuple[str, ...] = ()
    knowledge_layers: tuple[str, ...] = ()
    architecture_topics: tuple[str, ...] = ()
    implementation_approaches: tuple[str, ...] = ()
    tradeoffs: tuple[str, ...] = ()
    performance_concerns: tuple[str, ...] = ()
    debugging_strategies: tuple[str, ...] = ()
    production_concerns: tuple[str, ...] = ()
    refactor_strategy: tuple[str, ...] = ()
    senior_review_questions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "label": self.label,
            "application": self.application,
            "area": self.area,
            "mode": self.mode,
            "parent_domains": list(self.parent_domains),
            "trigger_terms": list(self.trigger_terms),
            "capabilities": list(self.capabilities),
            "responsibilities": list(self.responsibilities),
            "required_context": list(self.required_context),
            "safe_patterns": list(self.safe_patterns),
            "validation_steps": list(self.validation_steps),
            "avoid": list(self.avoid),
            "required_services": list(self.required_services),
            "knowledge_layers": list(self.knowledge_layers),
            "architecture_topics": list(self.architecture_topics),
            "implementation_approaches": list(self.implementation_approaches),
            "tradeoffs": list(self.tradeoffs),
            "performance_concerns": list(self.performance_concerns),
            "debugging_strategies": list(self.debugging_strategies),
            "production_concerns": list(self.production_concerns),
            "refactor_strategy": list(self.refactor_strategy),
            "senior_review_questions": list(self.senior_review_questions),
        }


@dataclass(frozen=True)
class ExpertMatch:
    expert: DomainExpert
    confidence: float
    evidence: tuple[str, ...] = ()
    intent: str = ""
    affected_elements: tuple[str, ...] = ()
    recommended_operations: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    fallbacks: tuple[str, ...] = ()
    expert_brief: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = self.expert.to_dict()
        data.update(
            {
                "confidence": round(float(self.confidence), 3),
                "evidence": list(self.evidence),
                "intent": self.intent,
                "current_system_summary": [],
                "affected_elements": list(self.affected_elements),
                "recommended_operations": list(self.recommended_operations),
                "assumptions": list(self.assumptions),
                "risks": list(self.risks),
                "fallbacks": list(self.fallbacks),
                "expert_brief": list(self.expert_brief),
            }
        )
        return data


EXPERT_KNOWLEDGE_PYRAMID = (
    "engine_or_application_foundation",
    "subsystem_semantics",
    "workflow_ownership",
    "architecture_and_boundaries",
    "implementation_paths",
    "optimization_and_scalability",
    "debugging_and_failure_modes",
    "production_pipeline_and_maintenance",
)

SENIOR_REVIEW_QUESTIONS = (
    "Is there a simpler solution that fits the same project constraints?",
    "Has this project already solved this problem in a reusable way?",
    "Should this live in a component, subsystem, data asset, graph, script, or pipeline step?",
    "What breaks when the project grows by 10x?",
    "What technical debt or maintenance burden does this introduce?",
    "Can another engineer or artist understand and safely modify this six months from now?",
    "What exact validation proves this is done?",
)

DEFAULT_IMPLEMENTATION_APPROACHES = (
    "reuse_existing_project_pattern",
    "registered_host_operation",
    "small_additive_change",
    "staged_plan_then_execute",
    "refactor_existing_implementation_when_present",
)

DEFAULT_TRADEOFFS = (
    "speed_to_prototype_vs_long_term_maintainability",
    "artist_friendly_controls_vs_system_complexity",
    "runtime_performance_vs_authoring_flexibility",
    "generic_reuse_vs_project_specific_convention",
)

DEFAULT_DEBUGGING_STRATEGIES = (
    "inspect_current_state_before_mutation",
    "trace_data_flow_or_call_flow",
    "isolate_minimal_reproduction",
    "validate_after_each_risky_step",
)

DEFAULT_PRODUCTION_CONCERNS = (
    "source_control_and_rollback",
    "naming_and_folder_conventions",
    "asset_references_and_redirects",
    "version_upgrade_risk",
    "team_handoff_documentation",
)


def _expert(
    domain: str,
    label: str,
    application: str,
    area: str,
    *,
    mode: str = "observe",
    parent_domains: tuple[str, ...] = (),
    trigger_terms: tuple[str, ...] = (),
    capabilities: tuple[str, ...] = (),
    responsibilities: tuple[str, ...] = (),
    required_context: tuple[str, ...] = (),
    safe_patterns: tuple[str, ...] = (),
    validation_steps: tuple[str, ...] = (),
    avoid: tuple[str, ...] = (),
    required_services: tuple[str, ...] = (),
    knowledge_layers: tuple[str, ...] = EXPERT_KNOWLEDGE_PYRAMID,
    architecture_topics: tuple[str, ...] = (),
    implementation_approaches: tuple[str, ...] = DEFAULT_IMPLEMENTATION_APPROACHES,
    tradeoffs: tuple[str, ...] = DEFAULT_TRADEOFFS,
    performance_concerns: tuple[str, ...] = (),
    debugging_strategies: tuple[str, ...] = DEFAULT_DEBUGGING_STRATEGIES,
    production_concerns: tuple[str, ...] = DEFAULT_PRODUCTION_CONCERNS,
    refactor_strategy: tuple[str, ...] = (),
    senior_review_questions: tuple[str, ...] = SENIOR_REVIEW_QUESTIONS,
) -> DomainExpert:
    return DomainExpert(
        domain=domain,
        label=label,
        application=application,
        area=area,
        mode=mode if mode in EXPERT_MODES else "observe",
        parent_domains=parent_domains,
        trigger_terms=trigger_terms,
        capabilities=capabilities,
        responsibilities=responsibilities,
        required_context=required_context,
        safe_patterns=safe_patterns,
        validation_steps=validation_steps,
        avoid=avoid,
        required_services=required_services,
        knowledge_layers=knowledge_layers,
        architecture_topics=architecture_topics,
        implementation_approaches=implementation_approaches,
        tradeoffs=tradeoffs,
        performance_concerns=performance_concerns,
        debugging_strategies=debugging_strategies,
        production_concerns=production_concerns,
        refactor_strategy=refactor_strategy,
        senior_review_questions=senior_review_questions,
    )


SHARED_GRAPH_CONTEXT = (
    "current selection or target graph",
    "node list with types and authored names",
    "upstream/downstream connection facts",
    "available operation schemas",
    "project naming/layout conventions",
)

SHARED_GRAPH_PATTERNS = (
    "Inspect graph topology before inserting or removing nodes.",
    "Prefer additive nodes and explicit reconnect plans over destructive rewires.",
    "Preserve existing authored connections unless the requested edit explicitly changes them.",
    "Keep graph layout readable after mutation.",
)

SHARED_GRAPH_VALIDATION = (
    "Query changed nodes and connections after the operation.",
    "Validate required inputs are connected or explicitly filled.",
    "Report unresolved pins, attributes, or data-flow gaps.",
)


DOMAIN_EXPERTS: tuple[DomainExpert, ...] = (
    _expert(
        "maya.node_editor",
        "Maya Node Editor Expert",
        "maya",
        "Node Editor",
        mode="advise",
        parent_domains=("maya", "maya.graph_systems"),
        trigger_terms=("node editor", "node network", "connect attr", "connect attribute", "connection editor", "utility node", "node graph"),
        capabilities=("inspect_network", "trace_connections", "plan_node_insertion", "validate_data_flow", "organize_layout"),
        responsibilities=(
            "Understand dependency graph nodes, attributes, and connection direction.",
            "Find safe insertion points without breaking existing graph behavior.",
            "Coordinate with more specific Maya experts when the graph belongs to materials, rigging, animation, or deformation.",
        ),
        required_context=SHARED_GRAPH_CONTEXT,
        safe_patterns=SHARED_GRAPH_PATTERNS,
        validation_steps=SHARED_GRAPH_VALIDATION,
        avoid=("Do not guess exact node or attribute names when scene context is available.",),
        required_services=("dcc_connection", "scene_context", "capability_graph", "maya_bridge"),
    ),
    _expert(
        "maya.hypershade",
        "Maya Hypershade Expert",
        "maya",
        "Hypershade",
        mode="observe",
        parent_domains=("maya", "maya.graph_systems", "maya.rendering"),
        trigger_terms=("hypershade", "shader", "shading", "material", "texture", "file node", "shading group", "surface shader", "arnold"),
        capabilities=("inspect_shader_network", "trace_texture_inputs", "plan_material_node_insertion", "validate_material_graph"),
        responsibilities=(
            "Identify material, texture, utility, and shading-group roles.",
            "Preserve existing material appearance while planning shader-network edits.",
            "Separate renderer-specific guidance from generic Maya graph guidance.",
        ),
        required_context=SHARED_GRAPH_CONTEXT + ("renderer and material type", "assigned meshes or shading groups"),
        safe_patterns=SHARED_GRAPH_PATTERNS + ("Preserve shading group assignments and existing file texture paths.",),
        validation_steps=SHARED_GRAPH_VALIDATION + ("Confirm material assignment and primary shader inputs after mutation.",),
        avoid=("Do not replace an existing shader network when an insertion or parameter edit is enough.",),
        required_services=("dcc_connection", "scene_context", "maya_bridge", "known_practice_playbooks"),
    ),
    _expert(
        "maya.rigging",
        "Maya Rigging Expert",
        "maya",
        "Rigging",
        mode="advise",
        parent_domains=("maya", "maya.character_systems"),
        trigger_terms=("rig", "rigging", "create_rig", "control", "joint", "skeleton", "ik", "fk", "constraint", "space switch", "orient", "matrix"),
        capabilities=("plan_rig_controls", "validate_joint_hierarchy", "plan_constraints", "preserve_animatable_controls"),
        responsibilities=(
            "Understand character hierarchy, controls, constraints, and animation-facing attributes.",
            "Preserve existing animation and rig behavior while adding modular controls.",
            "Prefer project rigging helpers and naming conventions over ad hoc scripts.",
        ),
        required_context=("current joint/control selection", "existing rig hierarchy", "naming conventions", "available rigging helper functions"),
        safe_patterns=("Use additive controls and constraints.", "Preserve transforms and offsets.", "Validate control/joint relationships after edits."),
        validation_steps=("Query created controls and constraints.", "Check required connections and transform offsets.", "Report any missing targets."),
        avoid=("Do not freeze, bake, delete, or rename rig elements without explicit approval.",),
        required_services=("dcc_connection", "scene_context", "project_index", "maya_bridge"),
    ),
    _expert(
        "maya.skinning",
        "Maya Skinning Expert",
        "maya",
        "Skinning",
        parent_domains=("maya", "maya.character_systems", "maya.deformation"),
        trigger_terms=("skin", "skinning", "skincluster", "weights", "bind skin", "influence", "deformer"),
        capabilities=("plan_bind_skin", "inspect_influences", "validate_skincluster", "preserve_weights"),
        responsibilities=("Protect existing weights and influence order.", "Validate mesh/joint inputs before skinning operations."),
        required_context=("target mesh", "joint/influence list", "existing skinCluster state", "bind pose"),
        safe_patterns=("Prefer non-destructive inspection before rebinding.", "Ask before replacing an existing skinCluster."),
        validation_steps=("Confirm skinCluster exists.", "Confirm expected influences are present.", "Report weight preservation risk."),
        avoid=("Do not rebind or overwrite weights without confirmation.",),
        required_services=("dcc_connection", "scene_context", "maya_bridge"),
    ),
    _expert(
        "maya.animation",
        "Maya Animation Expert",
        "maya",
        "Animation",
        parent_domains=("maya", "maya.character_systems"),
        trigger_terms=("animation", "keyframe", "graph editor", "time editor", "anim layer", "curve", "tangent"),
        capabilities=("inspect_animation_curves", "plan_keyframe_edits", "validate_timing"),
        responsibilities=("Understand animation curves, tangents, layers, and time ranges.", "Preserve authored motion unless explicitly changing it."),
        required_context=("selected controls", "current time range", "animation layers", "keyed attributes"),
        safe_patterns=("Preview or report curve edits before destructive changes.", "Respect selected time range and animation layers."),
        validation_steps=("Query edited keys/curves.", "Report frame range and affected attributes."),
        avoid=("Do not bake or delete keys without explicit approval.",),
        required_services=("dcc_connection", "scene_context", "maya_bridge"),
    ),
    _expert(
        "maya.scene_assembly",
        "Maya Scene Assembly Expert",
        "maya",
        "Scene Assembly",
        parent_domains=("maya", "maya.scene_systems"),
        trigger_terms=("outliner", "reference", "namespace", "usd", "assembly", "scene", "import", "export"),
        capabilities=("inspect_scene_structure", "plan_references", "validate_namespaces", "trace_asset_paths"),
        responsibilities=("Understand references, namespaces, hierarchy, scene organization, and USD handoff concerns."),
        required_context=("scene path", "references", "namespaces", "selection", "project path conventions"),
        safe_patterns=("Prefer reference-aware edits.", "Preserve namespaces and external asset links."),
        validation_steps=("Query references/namespaces after edits.", "Report unresolved or missing asset paths."),
        avoid=("Do not import, unload, replace, or rename references without confirmation.",),
        required_services=("dcc_connection", "scene_context", "project_index", "maya_bridge"),
    ),
    _expert(
        "maya.scripting",
        "Maya Python/MEL Expert",
        "maya",
        "Scripting",
        mode="advise",
        parent_domains=("maya", "code"),
        trigger_terms=("maya.cmds", "openmaya", "maya.api.openmaya", "mel", "script", "python"),
        capabilities=("select_host_api", "validate_command_args", "prefer_registered_operations", "generate_safe_scripts"),
        responsibilities=("Choose between maya.cmds, maya.api.OpenMaya, maya.OpenMaya, and MEL based on the operation."),
        required_context=("target Maya version", "command/API availability", "selection or object names", "existing helper functions"),
        safe_patterns=("Use registered bridge operations before generated scripts.", "Keep generated scripts small and inspectable."),
        validation_steps=("Run readback query after script execution.", "Report created/changed object names."),
        avoid=("Do not run broad scene scripts without target resolution.",),
        required_services=("dcc_operation_service", "maya_bridge", "project_index"),
    ),
    _expert(
        "unreal.blueprint_graph",
        "Unreal Blueprint Graph Expert",
        "unreal",
        "Blueprint Graphs",
        mode="advise",
        parent_domains=("unreal", "unreal.graph_systems"),
        trigger_terms=("blueprint", "bp", "event graph", "function graph", "macro graph", "pin", "node"),
        capabilities=("inspect_blueprint_graph", "author_function_graph", "author_member_variables", "plan_node_insertion", "validate_pins", "compile_blueprint", "layout_graph"),
        responsibilities=("Understand Blueprint node roles, exec/data pins, graph context, and compile impact."),
        required_context=("asset path", "graph name", "node list", "pin connections", "compile status"),
        safe_patterns=(
            "Open asset before mutation.",
            "Plan exact node/pin edits before applying.",
            "Use BlueprintGraphEditor and BlueprintGraphPinLibrary reflected helpers for graph authoring and readback.",
            "Lay out exec flow left-to-right on a stable grid, place data nodes near consumers, separate branches vertically, and group each feature in a named comment.",
        ),
        validation_steps=(
            "Compile Blueprint.",
            "Check graph diff and unresolved pins.",
            "Check node bounds for overlap and verify readable flow direction.",
            "Report rollback token when available.",
        ),
        avoid=(
            "Do not silently delete or reconnect existing Blueprint nodes.",
            "Do not use removed BlueprintEditorLibrary.get_blueprint_variables or get_blueprint_functions APIs.",
            "Do not treat InputMappingContext.mappings as authoritative on UE 5.8; inspect default_key_mappings.mappings.",
        ),
        required_services=("unreal_bridge", "semantic_graph_service", "capability_graph", "graph_patch_service", "blueprint_graph_knowledge_service"),
        architecture_topics=("Gameplay Framework", "Actor Components", "Subsystems", "Interfaces", "Event Dispatchers", "Gameplay Tags", "Data Assets", "Save Systems"),
        implementation_approaches=("inspect_existing_graph", "component_or_subsystem_extraction", "interface_or_dispatcher_communication", "data_asset_driven_configuration", "minimal_node_patch"),
        tradeoffs=("Blueprint_iteration_speed_vs_cpp_runtime_control", "component_reuse_vs_actor_specific_logic", "direct_references_vs_interfaces_or_dispatchers", "data_driven_design_vs_debuggability"),
        performance_concerns=("tick elimination", "Blueprint VM cost", "circular references and GC pressure", "actor/component lifetime", "async loading and soft references"),
        debugging_strategies=("check unresolved pins", "trace execution flow", "detect circular references", "review latent actions/timers", "check construction script side effects"),
        production_concerns=("cooking/packaging", "redirector cleanup", "plugin dependencies", "Blueprint merge conflict risk", "migration/version upgrade risk"),
        refactor_strategy=("map existing Blueprint behavior", "extract reusable Actor Components first", "promote global ownership to Subsystems when justified", "preserve gameplay behavior before changing architecture"),
    ),
    _expert(
        "unreal.control_rig",
        "Unreal Control Rig Expert",
        "unreal",
        "Control Rig",
        parent_domains=("unreal", "unreal.animation", "unreal.graph_systems"),
        trigger_terms=("control rig", "controlrig", "rig graph", "full body ik", "fk control", "ik control"),
        capabilities=("inspect_control_rig_graph", "plan_rig_units", "validate_controls", "compile_control_rig"),
        responsibilities=("Understand rig units, hierarchy, controls, spaces, and animation-facing behavior."),
        required_context=("control rig asset", "hierarchy", "graph nodes", "control names", "compile status"),
        safe_patterns=("Preserve authored controls and spaces.", "Use additive rig units when possible."),
        validation_steps=("Compile Control Rig.", "Validate created controls and required graph connections."),
        avoid=("Do not rename controls or break existing rig hierarchy without approval.",),
        required_services=("unreal_bridge", "semantic_graph_service", "capability_graph"),
    ),
    _expert(
        "unreal.niagara",
        "Unreal Niagara Expert",
        "unreal",
        "Niagara",
        parent_domains=("unreal", "unreal.vfx"),
        trigger_terms=("niagara", "emitter", "particle", "vfx", "system asset"),
        capabilities=("inspect_niagara_system", "plan_user_parameters", "validate_emitter_setup"),
        responsibilities=("Understand Niagara systems, emitters, user parameters, and attachment/activation patterns."),
        required_context=("Niagara asset path", "target actor/socket", "parameters", "activation trigger"),
        safe_patterns=("Expose user parameters for animation/gameplay control.", "Attach through sockets/components rather than hardcoded transforms when possible."),
        validation_steps=("Verify asset exists.", "Verify target attachment and expected parameters."),
        avoid=("Do not hardcode character asset names if selection/context can resolve them.",),
        required_services=("unreal_bridge", "capability_graph", "task_playbook_service"),
    ),
    _expert(
        "unreal.materials",
        "Unreal Materials Expert",
        "unreal",
        "Materials",
        parent_domains=("unreal", "unreal.rendering", "unreal.graph_systems"),
        trigger_terms=("material", "material instance", "shader", "texture", "parameter", "node"),
        capabilities=("inspect_material_graph", "plan_material_nodes", "validate_material_compile"),
        responsibilities=("Understand material nodes, parameters, instances, texture sampling, and performance tradeoffs."),
        required_context=("material asset", "node graph", "parameters", "texture references", "compile status"),
        safe_patterns=("Prefer material instances and parameters for tunable values.", "Preserve existing output behavior."),
        validation_steps=("Compile material.", "Report changed parameters/nodes and texture references."),
        avoid=("Do not replace the material graph when a parameter or instance edit is enough.",),
        required_services=("unreal_bridge", "semantic_graph_service", "capability_graph"),
    ),
    _expert(
        "python.code",
        "General Python Code Expert",
        "python",
        "Code",
        mode="advise",
        parent_domains=("code",),
        trigger_terms=("python", "function", "class", "test", "docstring", "refactor", ".py"),
        capabilities=("inspect_code", "plan_patch", "validate_compile", "preserve_style"),
        responsibilities=("Understand code structure, local patterns, tests, and safe patch scope."),
        required_context=("target file", "symbol context", "existing tests", "project conventions"),
        safe_patterns=("Patch narrowly.", "Prefer existing helpers and tests.", "Report validation evidence."),
        validation_steps=("Run py_compile or focused tests when possible.",),
        avoid=("Do not rewrite unrelated code.",),
        required_services=("project_index", "apply_patch", "test_runner"),
    ),
    _expert(
        "python.ui_integration",
        "Python Qt/UI Integration Expert",
        "python",
        "UI Integration",
        mode="advise",
        parent_domains=("code", "python.code"),
        trigger_terms=(
            "qt",
            "pyside",
            "pyqt",
            "qwidget",
            "window",
            "dialog",
            "button",
            "menu",
            "toolbar",
            "status",
            "chat",
            "sidebar",
            "maya ui",
        ),
        capabilities=("inspect_ui_patterns", "plan_widget_lifecycle", "preserve_existing_styles", "validate_ui_wiring"),
        responsibilities=(
            "Find existing UI classes, styling, lifecycle, and signal/slot patterns before adding widgets.",
            "Keep UI code integrated with existing status, logging, menu, and host-parenting systems.",
            "Protect responsiveness by avoiding blocking work in widget handlers.",
        ),
        required_context=("target window/widget class", "existing UI helper classes", "signal/slot lifecycle", "threading or worker boundary", "style conventions"),
        safe_patterns=("Reuse shared UI wrappers.", "Keep widget construction small and deterministic.", "Route long work through existing workers or services."),
        validation_steps=("Compile changed Python files.", "Instantiate or smoke-test UI helpers where possible.", "Verify signal wiring and duplicate-window behavior."),
        avoid=("Do not create a second UI framework or duplicate an existing menu/window registry.",),
        required_services=("project_index", "ui_framework", "test_runner"),
        architecture_topics=("Qt object ownership", "signal/slot boundaries", "host application parenting", "non-blocking UI handlers", "menu and toolbar registration"),
        implementation_approaches=("reuse_existing_widget_base", "adapter_around_existing_function", "typed_argument_controls", "background_worker_for_slow_work"),
        tradeoffs=("fast_widget_addition_vs_consistent_lifecycle", "generic_form_generation_vs_artist_friendly_controls", "inline_logic_vs_service_boundary"),
        performance_concerns=("main_thread_blocking", "slow_menu_population", "large_text_rendering", "expensive_startup_work"),
        debugging_strategies=("trace signal emissions", "verify parent ownership", "profile handler duration", "watch UI heartbeat diagnostics"),
    ),
    _expert(
        "python.testing_validation",
        "Python Testing and Validation Expert",
        "python",
        "Testing / Validation",
        mode="advise",
        parent_domains=("code", "python.code"),
        trigger_terms=(
            "test",
            "tests",
            "unittest",
            "pytest",
            "compile",
            "py_compile",
            "validate",
            "validation",
            "smoke",
            "regression",
            "verify",
        ),
        capabilities=("select_focused_tests", "plan_static_validation", "separate_runtime_validation", "define_regression_coverage"),
        responsibilities=(
            "Choose the smallest useful validation set for a code edit.",
            "Separate static verification from Maya, Unreal, or other host-runtime verification.",
            "Add regression tests for the behavior changed rather than broad brittle coverage.",
        ),
        required_context=("changed files", "existing test patterns", "host runtime availability", "validation commands", "expected failure modes"),
        safe_patterns=("Run py_compile for changed Python files.", "Prefer focused unit tests.", "Report unproven host-runtime behavior explicitly."),
        validation_steps=("Compile modified Python files.", "Run focused tests.", "Document any skipped runtime validation."),
        avoid=("Do not claim host-runtime verification from static tests alone.",),
        required_services=("project_index", "test_runner", "host_status"),
        architecture_topics=("test seams", "mockable service boundaries", "host-free unit coverage", "runtime smoke validation"),
        implementation_approaches=("focused_regression_test", "static_compile_gate", "host_runtime_smoke_check", "fixture_or_stub_for_external_app"),
        tradeoffs=("fast_feedback_vs_integration_confidence", "mocked_tests_vs_live_host_truth", "broad_coverage_vs_stability"),
    ),
    _expert(
        "python.async_responsiveness",
        "Python Async/UI Responsiveness Expert",
        "python",
        "Responsiveness",
        mode="advise",
        parent_domains=("code", "python.code"),
        trigger_terms=(
            "freeze",
            "hang",
            "not responding",
            "responsive",
            "slow",
            "timeout",
            "thread",
            "worker",
            "background",
            "subprocess",
            "streaming",
            "daemon",
            "watchdog",
            "heartbeat",
        ),
        capabilities=("identify_main_thread_risk", "plan_worker_boundary", "add_progress_heartbeat", "bound_slow_operations"),
        responsibilities=(
            "Find disk, network, subprocess, model, and large-render work that could run on the UI thread.",
            "Move slow work behind existing worker/service boundaries and emit visible progress.",
            "Use bounded timeouts, staged calls, and diagnostic breadcrumbs for long operations.",
        ),
        required_context=("call path from UI event", "thread or worker ownership", "timeout behavior", "diagnostic report", "progress surface"),
        safe_patterns=("Acknowledge user input immediately.", "Emit stage progress before slow calls.", "Keep subprocess and indexing work off the main thread."),
        validation_steps=("Run responsiveness-focused tests.", "Check diagnostic heartbeat output.", "Confirm UI handler does not call blocking work directly."),
        avoid=("Do not hide long-running work behind a silent status line.",),
        required_services=("diagnostics", "worker_threads", "status_reporting", "test_runner"),
        architecture_topics=("UI event loop", "worker isolation", "model-call chunking", "incremental rendering", "backpressure"),
        implementation_approaches=("queued_background_worker", "staged_model_call", "progress_callback", "timeout_and_fallback", "debounced_render_or_search"),
        performance_concerns=("main_thread_blocking", "disk_saturation", "large_chat_render", "menu_population_latency", "long_local_model_inference"),
        debugging_strategies=("instrument handler duration", "compare heartbeat timestamps", "isolate subprocess waits", "replay long prompt smoke cases"),
    ),
    _expert(
        "python.index_search",
        "Python Index/Search Expert",
        "python",
        "Indexing / Search",
        mode="advise",
        parent_domains=("code", "python.code", "project.search"),
        trigger_terms=(
            "index",
            "indexing",
            "search",
            "symbol",
            "symbols",
            "fts",
            "sqlite",
            "dependency graph",
            "call graph",
            "asset mention",
            "@",
        ),
        capabilities=("inspect_index_lifecycle", "rank_project_matches", "preserve_index_schema", "separate_bootstrap_from_rich_indexing"),
        responsibilities=(
            "Keep project search deterministic, fast, and grounded in current index freshness.",
            "Separate quick symbol bootstrap from richer dependency/search table builds.",
            "Ensure mention and asset search use scoped candidates instead of broad guesses.",
        ),
        required_context=("index path", "index freshness", "query scope", "symbol/chunk tables", "candidate ranking evidence"),
        safe_patterns=("Use stale-only indexing when possible.", "Keep noisy progress out of chat.", "Report index readiness accurately."),
        validation_steps=("Run index/search regression tests.", "Verify returned candidates exist.", "Check status text for in-progress vs ready state."),
        avoid=("Do not perform broad disk walks from UI handlers.",),
        required_services=("project_index", "knowledge_background_service", "asset_mention_service"),
        architecture_topics=("incremental indexing", "FTS tables", "symbol graph", "dependency graph", "scoped query planning"),
        implementation_approaches=("bootstrap_then_background_enrich", "cached_query_results", "rank_exact_symbols_first", "filter_external_dependencies"),
        performance_concerns=("disk_saturation", "startup_index_cost", "large_result_rendering", "SQLite locking"),
    ),
    _expert(
        "python.patch_application",
        "Python Patch Application Expert",
        "python",
        "Patch / Change Safety",
        mode="advise",
        parent_domains=("code", "python.code"),
        trigger_terms=(
            "patch",
            "diff",
            "apply",
            "modify_file",
            "create_file",
            "rollback",
            "undo",
            "change session",
            "preview",
            "xml",
        ),
        capabilities=("validate_patch_scope", "preview_changes", "preserve_user_changes", "plan_rollback", "repair_unpatchable_output"),
        responsibilities=(
            "Ensure generated code edits are previewable, narrowly scoped, and reversible.",
            "Reject prose-only or unpatchable model responses before mutation.",
            "Preserve unrelated user changes and report rollback paths.",
        ),
        required_context=("project root", "patch tags", "target file contents", "change history session", "validation results"),
        safe_patterns=("Preview before applying.", "Use exact original blocks.", "Create undo sessions for applied changes."),
        validation_steps=("Parse model response into file changes.", "Validate paths stay inside allowed roots.", "Run static validation after apply."),
        avoid=("Do not apply broad rewrites without exact scoped evidence.",),
        required_services=("project_edit_agent_service", "change_history_service", "path_validator", "test_runner"),
        architecture_topics=("diff preview", "path safety", "undo session persistence", "model output contracts"),
        implementation_approaches=("xml_patch_contract", "resilient_block_replacement", "preview_then_apply", "validation_gate_after_apply"),
        debugging_strategies=("inspect parser errors", "compare original block mismatch", "check path normalization", "verify change session contents"),
    ),
    _expert(
        "pipeline.composition",
        "Pipeline Composition Expert",
        "pipeline",
        "Pipeline Graph",
        mode="advise",
        parent_domains=("pipeline",),
        trigger_terms=("pipeline", "node graph", "workflow", "connect", "add and connect", "compile", "data flow"),
        capabilities=("inspect_pipeline_graph", "plan_node_connections", "validate_required_inputs", "report_broken_flow"),
        responsibilities=("Understand node data flow, required attributes, compile gates, and cross-tool execution order."),
        required_context=("current graph", "node schemas", "required inputs", "existing connections", "compile result"),
        safe_patterns=("Highlight unresolved nodes before execution.", "Use existing context when connecting related functions."),
        validation_steps=("Validate required node inputs.", "Report disconnected required flow and unresolved attributes."),
        avoid=("Do not imply a graph is runnable while required inputs are missing.",),
        required_services=("pipeline_node_view", "workflow_service", "argument_validator"),
    ),
    _expert(
        "project.search",
        "Project Search Expert",
        "project",
        "Search / Symbols",
        mode="advise",
        parent_domains=("project",),
        trigger_terms=("find", "search", "symbol", "where", "existing", "similar", "project"),
        capabilities=("scope_search", "rank_exact_matches", "find_reusable_code", "report_evidence"),
        responsibilities=("Find exact project facts before guessing, including similar implementations and conventions."),
        required_context=("active project root", "index freshness", "current file/selection", "query terms"),
        safe_patterns=("Prefer deterministic project index and exact symbol names.", "Report source paths for evidence."),
        validation_steps=("Confirm referenced files/symbols exist.",),
        avoid=("Do not invent assets, symbols, or APIs when search can verify them.",),
        required_services=("project_index", "symbol_search", "asset_mention_service"),
    ),
)


BROAD_DOMAIN_CATALOG: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "maya": (
        ("graph_editor", "Graph Editor", ("graph editor", "animation curve", "anim curve", "tangent", "keyframe")),
        ("outliner", "Outliner", ("outliner", "hierarchy", "parent", "group", "scene tree")),
        ("connection_editor", "Connection Editor", ("connection editor", "connect attribute", "disconnect", "source attribute", "destination attribute")),
        ("shape_editor", "Shape Editor", ("shape editor", "blendshape", "target shape", "corrective", "facial")),
        ("time_editor", "Time Editor", ("time editor", "clip", "animation clip", "composition")),
        ("bifrost", "Bifrost", ("bifrost", "graph compound", "simulation graph")),
        ("xgen", "XGen", ("xgen", "groom", "hair", "fur", "description")),
        ("rendering", "Rendering", ("render", "render setup", "render layer", "camera", "lighting")),
        ("modeling", "Modeling", ("modeling", "mesh", "poly", "extrude", "bevel", "uv")),
        ("deformation", "Deformation", ("deformer", "deformation", "blendshape", "lattice", "wrap")),
        ("constraints", "Constraints", ("constraint", "parent constraint", "orient constraint", "point constraint", "aim constraint")),
        ("referencing", "Referencing", ("reference", "namespace", "referenced asset", "reload reference")),
        ("usd", "USD", ("usd", "stage", "layer", "payload", "variant")),
        ("mel", "MEL", ("mel", "mel command", "mel script")),
    ),
    "unreal": (
        ("animation_blueprint", "Animation Blueprint", ("animation blueprint", "anim blueprint", "anim graph", "state machine")),
        ("pcg", "PCG", ("pcg", "procedural content", "pcg graph")),
        ("behavior_tree", "Behavior Tree", ("behavior tree", "blackboard", "task node", "decorator")),
        ("state_tree", "State Tree", ("state tree", "state transition", "evaluator")),
        ("metasounds", "MetaSounds", ("metasound", "audio graph", "sound source")),
        ("sequencer", "Sequencer", ("sequencer", "level sequence", "movie scene", "track")),
        ("gameplay_ability_system", "Gameplay Ability System", ("gas", "gameplay ability", "ability system", "gameplay effect", "attribute set")),
        ("enhanced_input", "Enhanced Input", ("enhanced input", "input action", "input mapping context")),
        ("replication", "Replication", ("replication", "replicated", "rpc", "authority", "network")),
        ("asset_management", "Asset Management", ("asset manager", "primary asset", "asset registry", "redirector")),
        ("editor_scripting", "Editor Scripting", ("editor scripting", "editor utility", "python", "blutility")),
        ("cpp", "C++", ("c++", "cpp", "uclass", "uproperty", "ufunction")),
        ("umg", "UMG / UI", ("umg", "widget blueprint", "user widget", "slate")),
        ("world_partition", "World Partition", ("world partition", "data layer", "streaming")),
        ("physics", "Physics", ("physics", "chaos", "collision", "constraint", "physical material")),
    ),
    "blender": (
        ("geometry_nodes", "Geometry Nodes", ("geometry nodes", "node group", "modifier nodes")),
        ("shader_nodes", "Shader Nodes", ("shader node", "material node", "principled", "texture")),
        ("modeling", "Modeling", ("modeling", "mesh", "edit mode", "bevel", "extrude")),
        ("rigging", "Rigging", ("armature", "bone", "pose", "constraint", "rig")),
        ("animation", "Animation", ("animation", "keyframe", "action", "fcurve", "nla")),
        ("grease_pencil", "Grease Pencil", ("grease pencil", "stroke", "drawing")),
        ("compositor", "Compositor", ("compositor", "composite node", "render layer")),
        ("rendering", "Rendering", ("cycles", "eevee", "render", "lighting", "camera")),
        ("uv_texturing", "UV / Texturing", ("uv", "unwrap", "texture paint", "image texture")),
        ("python_api", "Python API", ("bpy", "blender python", "operator", "addon")),
    ),
    "houdini": (
        ("sops", "SOPs / Geometry", ("sop", "geometry node", "attribute wrangle", "vex")),
        ("dops", "DOPs / Simulation", ("dop", "simulation", "pyro", "vellum", "flip")),
        ("lops_usd", "LOPs / Solaris / USD", ("lop", "solaris", "usd", "stage", "karma")),
        ("chops", "CHOPs", ("chop", "channel", "motion fx")),
        ("materials", "Materials", ("material", "shader", "vop", "karma material")),
        ("pdg", "PDG / TOPs", ("pdg", "top", "work item", "scheduler")),
        ("hda", "HDAs", ("hda", "digital asset", "parameter interface")),
        ("python_hou", "Python hou API", ("hou.", "houdini python", "python shell")),
    ),
    "substance_painter": (
        ("texture_sets", "Texture Sets", ("texture set", "uv tile", "udim")),
        ("layers_masks", "Layers and Masks", ("layer", "mask", "generator", "fill layer")),
        ("materials", "Materials", ("material", "smart material", "sbsar")),
        ("baking", "Baking", ("bake", "mesh maps", "normal map", "ao")),
        ("exports", "Texture Export", ("export textures", "export preset", "packed maps")),
        ("python_api", "Python API", ("substance painter python", "python api", "plugin")),
    ),
    "motionbuilder": (
        ("characters", "Characters", ("character", "characterize", "control rig")),
        ("retargeting", "Retargeting", ("retarget", "source character", "target character")),
        ("takes", "Takes", ("take", "story", "clip")),
        ("constraints", "Constraints", ("constraint", "relation constraint", "parent child")),
        ("mocap_cleanup", "Mocap Cleanup", ("mocap", "filter", "plot", "cleanup")),
        ("python_api", "Python API", ("pyfbsdk", "motionbuilder python", "fbmodel")),
    ),
    "unity": (
        ("scene_gameobjects", "Scene / GameObjects", ("gameobject", "scene", "component", "transform")),
        ("prefabs", "Prefabs", ("prefab", "variant", "nested prefab")),
        ("materials_shaders", "Materials / Shaders", ("material", "shader graph", "texture")),
        ("animation", "Animation", ("animator", "animation clip", "timeline", "controller")),
        ("vfx_graph", "VFX Graph", ("vfx graph", "visual effect", "particle")),
        ("addressables", "Addressables", ("addressable", "asset bundle", "group")),
        ("editor_scripting", "Editor Scripting", ("editor script", "asset database", "menu item")),
        ("csharp", "C#", ("c#", "csharp", "monobehaviour", "scriptableobject")),
    ),
    "github": (
        ("repositories", "Repositories", ("repository", "repo", "clone", "remote")),
        ("pull_requests", "Pull Requests", ("pull request", "pr", "review")),
        ("issues", "Issues", ("issue", "label", "milestone")),
        ("actions", "Actions / CI", ("github actions", "workflow", "ci", "runner")),
    ),
    "perforce": (
        ("workspaces", "Workspaces", ("workspace", "client", "p4client")),
        ("changelists", "Changelists", ("changelist", "shelve", "submit")),
        ("streams", "Streams", ("stream", "branch", "integrate")),
    ),
    "slack": (
        ("messaging", "Messaging", ("slack", "channel", "thread", "mention")),
        ("notifications", "Notifications", ("webhook", "bot token", "pipeline alert")),
    ),
    "discord": (
        ("messaging", "Messaging", ("discord", "guild", "channel", "thread")),
        ("notifications", "Notifications", ("webhook", "bot token", "pipeline alert")),
    ),
    "atlassian": (
        ("jira", "Jira", ("jira", "issue", "project key", "ticket")),
        ("confluence", "Confluence", ("confluence", "space", "page", "documentation")),
    ),
    "mobile": (
        ("pairing", "Mobile Pairing", ("qr", "pair", "mobile app", "token")),
        ("remote_view", "Remote View", ("view pc", "screen", "application progress")),
        ("jobs", "Jobs", ("job", "finished jobs", "kick off", "output log")),
    ),
    "pipeline": (
        ("validation", "Pipeline Validation", ("validate", "required input", "broken flow", "compile")),
        ("job_reporting", "Job Reporting", ("job report", "output log", "files edited", "failed")),
        ("node_details", "Node Details", ("node attributes", "function details", "context selection")),
    ),
}


def _catalog_expert(application: str, key: str, label: str, trigger_terms: tuple[str, ...]) -> DomainExpert:
    is_graph = any(term in " ".join(trigger_terms).lower() for term in ("node", "graph", "shader", "material", "blueprint"))
    capabilities = (
        "inspect_context",
        "identify_safe_edit_path",
        "apply_best_practices",
        "define_validation_steps",
    )
    if is_graph:
        capabilities = capabilities + ("trace_connections", "validate_data_flow", "organize_layout")
    return _expert(
        f"{application}.{key}",
        f"{label} Expert" if not label.endswith("Expert") else label,
        application,
        label,
        parent_domains=(application,),
        trigger_terms=trigger_terms + (label.lower(), key.replace("_", " ")),
        capabilities=capabilities,
        responsibilities=(
            f"Understand {label} workflows, terminology, common failure modes, and safe edit patterns.",
            "Route execution through existing registered services and bridges instead of owning mutation.",
            "Separate general best practice from project conventions and user preferences.",
        ),
        required_context=(
            "active application/version",
            "current selection or target asset",
            "project conventions",
            "available operation schemas",
        ),
        safe_patterns=(
            "Inspect current state before planning changes.",
            "Prefer additive, reversible changes.",
            "Ask for missing target context before risky mutation.",
        ),
        validation_steps=(
            "Query or inspect the changed state after execution.",
            "Report exact affected assets, objects, nodes, files, or messages.",
            "Surface unresolved assumptions or validation gaps.",
        ),
        avoid=(
            "Do not bypass stable existing execution handlers.",
            "Do not infer exact target names when the project or host can be queried.",
        ),
        required_services=("project_context", "registered_operations", f"{application}_bridge_or_api"),
        architecture_topics=_architecture_topics_for(application, key, label),
        implementation_approaches=_implementation_approaches_for(application, key, label),
        tradeoffs=_tradeoffs_for(application, key, label),
        performance_concerns=_performance_concerns_for(application, key, label),
        debugging_strategies=_debugging_strategies_for(application, key, label),
        production_concerns=_production_concerns_for(application, key, label),
        refactor_strategy=_refactor_strategy_for(application, key, label),
    )


def _architecture_topics_for(application: str, key: str, label: str) -> tuple[str, ...]:
    text = f"{application}.{key}.{label}".lower()
    if application == "unreal" and any(term in text for term in ("blueprint", "gameplay", "ability", "input", "replication")):
        return (
            "Gameplay Framework",
            "Actor Components",
            "Subsystems",
            "Interfaces",
            "Event Dispatchers",
            "Gameplay Tags",
            "Data Assets",
            "Save/Load boundaries",
        )
    if application == "maya" and any(term in text for term in ("rig", "node", "constraint", "deform", "skin")):
        return (
            "Dependency Graph",
            "Evaluation Manager",
            "Matrix workflows",
            "Offset Parent Matrix",
            "Custom nodes",
            "Parallel Evaluation",
            "Undo chunks",
        )
    if application in {"blender", "houdini"} and any(term in text for term in ("node", "sop", "geometry", "shader")):
        return (
            "Procedural graph ownership",
            "Attribute/data flow",
            "Reusable node groups/assets",
            "Viewport vs render evaluation",
            "Cache boundaries",
        )
    if application in {"github", "perforce"}:
        return ("branching strategy", "review workflow", "changelist ownership", "rollback strategy", "CI gates")
    if application in {"slack", "discord", "atlassian"}:
        return ("notification routing", "human approval loops", "auditability", "thread/project context", "permission boundaries")
    return ("subsystem ownership", "data flow", "integration boundaries", "validation gates", "handoff points")


def _implementation_approaches_for(application: str, key: str, label: str) -> tuple[str, ...]:
    base = DEFAULT_IMPLEMENTATION_APPROACHES
    text = f"{application}.{key}.{label}".lower()
    if "graph" in text or "node" in text or "shader" in text:
        return base + ("inspect_existing_graph", "insert_minimal_nodes", "preserve_existing_connections", "layout_after_edit")
    if "replication" in text or "network" in text:
        return base + ("server_authoritative_design", "replicated_state_model", "rpc_boundary_definition", "prediction_or_reconciliation_plan")
    if "rig" in text or "animation" in text:
        return base + ("preserve_authored_motion", "additive_layer_or_control", "export_runtime_contract")
    return base


def _tradeoffs_for(application: str, key: str, label: str) -> tuple[str, ...]:
    text = f"{application}.{key}.{label}".lower()
    values = list(DEFAULT_TRADEOFFS)
    if application == "unreal":
        values.extend(("Blueprint_iteration_speed_vs_cpp_runtime_control", "component_reuse_vs_actor_specific_logic", "data_driven_design_vs_debuggability"))
    if "replication" in text or "network" in text:
        values.extend(("bandwidth_vs_responsiveness", "prediction_complexity_vs_input_feel", "authority_safety_vs_client_responsiveness"))
    if application == "maya":
        values.extend(("rig_flexibility_vs_evaluation_cost", "node_network_clarity_vs_compactness", "artist_control_vs_pipeline_constraints"))
    return tuple(values)


def _performance_concerns_for(application: str, key: str, label: str) -> tuple[str, ...]:
    text = f"{application}.{key}.{label}".lower()
    concerns = ["avoid unnecessary per-frame work", "watch memory/reference growth", "validate scalability on representative assets"]
    if application == "unreal":
        concerns.extend(("tick elimination", "Blueprint VM cost", "actor/component lifetime", "async loading", "asset streaming"))
    if "material" in text or "shader" in text:
        concerns.extend(("shader permutations", "texture streaming", "sampler limits", "instruction count"))
    if "niagara" in text or "vfx" in text:
        concerns.extend(("CPU vs GPU emitter cost", "spawn/update script cost", "scalability settings", "bounds/culling"))
    if application == "maya":
        concerns.extend(("DG cycles", "parallel evaluation blockers", "heavy expressions/callbacks", "deformer stack cost"))
    if application == "houdini":
        concerns.extend(("cook time", "cache invalidation", "attribute bloat", "PDG work item fan-out"))
    return tuple(dict.fromkeys(concerns))


def _debugging_strategies_for(application: str, key: str, label: str) -> tuple[str, ...]:
    strategies = list(DEFAULT_DEBUGGING_STRATEGIES)
    text = f"{application}.{key}.{label}".lower()
    if application == "unreal":
        strategies.extend(("inspect logs/compile output", "check construction script side effects", "verify authority/ownership", "profile with Unreal Insights"))
    if "blueprint" in text or "graph" in text:
        strategies.extend(("check unresolved pins", "trace execution flow", "detect circular references", "review latent actions/timers"))
    if application == "maya":
        strategies.extend(("query connections and node types", "check evaluation cycles", "inspect undo safety", "validate selection assumptions"))
    return tuple(dict.fromkeys(strategies))


def _production_concerns_for(application: str, key: str, label: str) -> tuple[str, ...]:
    concerns = list(DEFAULT_PRODUCTION_CONCERNS)
    if application == "unreal":
        concerns.extend(("cooking/packaging", "redirector cleanup", "plugin dependencies", "migration/version upgrade risk", "merge conflict risk"))
    if application == "maya":
        concerns.extend(("reference/namespace safety", "publish validation", "export contracts", "farm/batch compatibility"))
    if application in {"github", "perforce"}:
        concerns.extend(("review ownership", "atomic commits/changelists", "CI validation", "revert/shelve path"))
    return tuple(dict.fromkeys(concerns))


def _refactor_strategy_for(application: str, key: str, label: str) -> tuple[str, ...]:
    text = f"{application}.{key}.{label}".lower()
    strategy = [
        "inspect_existing_implementation_before_rebuilding",
        "preserve_external_behavior",
        "make_one_reversible_change_at_a_time",
        "validate_equivalence_after_refactor",
    ]
    if application == "unreal":
        strategy.extend(("move repeated Blueprint logic into Components or Subsystems when justified", "convert constants to Data Assets/Tables where project scale warrants it"))
    if application == "maya":
        strategy.extend(("wrap repeated scripts into reusable project helpers", "preserve scene compatibility and namespace behavior"))
    return tuple(strategy)


PRODUCTION_SYSTEM_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "domain": "production.character_locomotion",
        "label": "Character Locomotion Systems Expert",
        "area": "Character Systems",
        "trigger_terms": ("locomotion", "motion matching", "pose search", "distance matching", "orientation warping", "stride warping", "motion warping", "root motion", "foot ik", "gait"),
        "architecture_topics": ("traditional state machines", "motion matching", "pose search databases", "root motion vs in-place", "IK and warping stack", "gameplay movement contract", "animation budget and scalability"),
        "implementation_approaches": ("state_machine_locomotion", "motion_matching_pose_search", "hybrid_layered_locomotion", "root_motion_with_gameplay_authority", "in_place_with_runtime_warping"),
    },
    {
        "domain": "production.traversal",
        "label": "Traversal Systems Expert",
        "area": "Traversal",
        "trigger_terms": ("traversal", "mantle", "mantling", "vault", "climb", "wall run", "ledge", "zipline", "ladder", "sliding", "parkour", "grappling hook"),
        "architecture_topics": ("ability/state ownership", "environment detection", "motion matching or montage playback", "root motion alignment", "IK/contact correction", "prediction and replication", "level-design authoring tools"),
        "implementation_approaches": ("animation_driven_traversal", "physics_assisted_traversal", "GAS_ability_per_traversal_action", "component_based_detection_and_execution", "data_asset_authored_traversal_rules"),
    },
    {
        "domain": "production.combat",
        "label": "Combat Systems Expert",
        "area": "Combat",
        "trigger_terms": ("combat", "souls-like", "soulslike", "melee", "combo", "parry", "block", "dodge", "roll", "hit reaction", "poise", "stagger", "finisher"),
        "architecture_topics": ("input buffering", "combo state", "damage model", "hit reaction and poise", "animation cancel rules", "target lock", "GAS or custom ability layer", "replication authority"),
        "implementation_approaches": ("GAS_ability_based_combat", "component_based_combat_framework", "data_asset_combo_trees", "animation_notify_driven_windows", "server_authoritative_hit_validation"),
    },
    {
        "domain": "production.shooter",
        "label": "Shooter Systems Expert",
        "area": "Shooter",
        "trigger_terms": ("shooter", "weapon", "hitscan", "projectile", "ballistics", "recoil", "ads", "reload", "magazine", "spread", "lag compensation"),
        "architecture_topics": ("weapon data model", "fire modes", "prediction and reconciliation", "server hit validation", "animation and reload state", "inventory/equipment integration", "anti-cheat and authority"),
        "implementation_approaches": ("hitscan_trace_authoritative", "projectile_actor_or_pooled_projectile", "data_driven_weapon_definitions", "predicted_client_fx_with_server_confirmation"),
    },
    {
        "domain": "production.inventory_ui",
        "label": "Inventory and UI Systems Expert",
        "area": "Inventory/UI",
        "trigger_terms": ("inventory", "equipment", "drag and drop", "hud", "ui", "widget", "radial menu", "accessibility", "localization"),
        "architecture_topics": ("data model vs presentation", "replicated inventory state", "drag/drop interaction model", "controller navigation", "save/load integration", "localization and accessibility"),
        "implementation_approaches": ("component_owned_inventory", "fast_array_replicated_items", "view_model_or_presenter_layer", "data_asset_item_definitions"),
    },
    {
        "domain": "production.networking",
        "label": "Networking Systems Expert",
        "area": "Networking",
        "trigger_terms": ("networking", "replication", "prediction", "rollback", "lag compensation", "fast array", "replication graph", "relevancy", "rpc"),
        "architecture_topics": ("server authority", "ownership", "RPC boundaries", "client prediction", "rollback/reconciliation", "Fast Array Replication", "Replication Graph", "network relevancy"),
        "implementation_approaches": ("server_authoritative_state", "client_predicted_input", "fast_array_state_replication", "relevancy_bounded_replication_graph"),
    },
    {
        "domain": "production.ai_systems",
        "label": "AI Systems Expert",
        "area": "AI",
        "trigger_terms": ("ai", "behavior tree", "state tree", "utility ai", "goap", "perception", "squad ai", "cover ai", "patrol", "tactical"),
        "architecture_topics": ("behavior trees vs state trees", "blackboard/data ownership", "perception and investigation", "navigation modifiers", "group coordination", "debug visualization"),
        "implementation_approaches": ("behavior_tree_blackboard", "state_tree_for_structured_agents", "utility_scoring_layer", "data_driven_tactical_behaviors"),
    },
    {
        "domain": "production.world_systems",
        "label": "Open World Systems Expert",
        "area": "World Systems",
        "trigger_terms": ("open world", "world partition", "streaming", "hlod", "checkpoint", "spawn system", "weather", "time of day", "population", "world persistence"),
        "architecture_topics": ("World Partition", "streaming and HLOD", "save/persistence", "spawn ownership", "large-world memory budgets", "AI population scheduling"),
        "implementation_approaches": ("data_layer_streaming", "world_partition_authoring", "persistent_world_state_registry", "spawn_manager_subsystem"),
    },
    {
        "domain": "production.character_pipeline",
        "label": "Character Pipeline Expert",
        "area": "Cross-App Character Pipeline",
        "trigger_terms": ("character pipeline", "maya to unreal", "fbx", "skeleton", "retarget", "control rig", "motion matching", "animation pipeline", "rig publishing"),
        "architecture_topics": ("Maya rig source", "FBX export contract", "Unreal skeleton import", "IK Rig/Retargeter", "Control Rig", "Motion Matching/Pose Search", "gameplay animation integration", "Sequencer/rendering handoff"),
        "implementation_approaches": ("validated_export_contract", "batch_retargeting_pipeline", "rig_publish_then_runtime_import", "project_specific_skeleton_standard"),
    },
    {
        "domain": "review.principal_engineer",
        "label": "Senior Review Expert",
        "application": "review",
        "area": "Principal Engineering Review",
        "trigger_terms": ("review", "architecture", "scalable", "maintainable", "technical debt", "best approach", "production ready", "refactor", "simpler solution"),
        "architecture_topics": ("system boundaries", "team maintainability", "project conventions", "future scale", "reversibility", "validation evidence"),
        "implementation_approaches": ("do_not_edit", "compare_options", "challenge_assumptions", "recommend_lowest_risk_next_step"),
    },
)


def _production_system_expert(spec: dict[str, Any]) -> DomainExpert:
    application = str(spec.get("application") or "production")
    return _expert(
        str(spec["domain"]),
        str(spec["label"]),
        application,
        str(spec["area"]),
        parent_domains=(application, "senior_systems"),
        trigger_terms=tuple(spec.get("trigger_terms") or ()),
        capabilities=("decompose_system_request", "compare_implementation_approaches", "assess_architecture_tradeoffs", "define_debugging_strategy", "define_validation_plan", "plan_refactor_without_rebuild"),
        responsibilities=(
            "Understand the complete production system, not only individual features or nodes.",
            "Compare multiple implementation approaches with pros, cons, scalability, and production risk.",
            "Integrate with existing project architecture instead of rebuilding when a compatible system exists.",
        ),
        required_context=("existing project architecture", "current implementation or prototype", "target engine/DCC version", "networking/performance constraints", "team workflow and validation expectations"),
        safe_patterns=("Inspect existing implementation before proposing a rebuild.", "Separate prototype path from production path.", "Define milestones, validation gates, and rollback points."),
        validation_steps=("Validate behavior against the requested gameplay/production contract.", "Check performance, networking, maintainability, and authoring workflow risks.", "Report which assumptions still require project evidence."),
        avoid=("Do not reduce a production-system request to a single script or graph edit.", "Do not claim AAA-quality without validation, profiling, and integration evidence.", "Do not rebuild an existing system without first comparing refactor options."),
        required_services=("project_index", "domain_experts", "task_playbook_service", "registered_operations"),
        architecture_topics=tuple(spec.get("architecture_topics") or ()),
        implementation_approaches=tuple(spec.get("implementation_approaches") or ()),
        tradeoffs=("prototype_speed_vs_production_architecture", "data_driven_authoring_vs_runtime_complexity", "network_correctness_vs_responsiveness", "AAA_feature_depth_vs_team_maintenance_cost"),
        performance_concerns=("runtime tick/update cost", "memory and asset lifetime", "network bandwidth and prediction overhead", "content scale and streaming", "profiling on representative scenarios"),
        debugging_strategies=("instrument state transitions", "capture representative failing scenario", "verify authority/ownership and data flow", "profile before optimizing", "compare against existing project patterns"),
        production_concerns=("source control and review plan", "milestone breakdown", "authoring tools and documentation", "migration path from prototype", "regression validation"),
        refactor_strategy=("map existing behavior", "identify reusable seams", "extract one subsystem/component at a time", "keep behavior equivalent before adding new capability", "validate with tests, editor checks, or gameplay smoke tests"),
    )


_SYSTEM_EXPERTS = tuple(_production_system_expert(spec) for spec in PRODUCTION_SYSTEM_CATALOG)


_REGISTERED_EXPERT_DOMAINS = {expert.domain for expert in DOMAIN_EXPERTS}
DOMAIN_EXPERTS = DOMAIN_EXPERTS + _SYSTEM_EXPERTS + tuple(
    expert
    for application, entries in BROAD_DOMAIN_CATALOG.items()
    for key, label, trigger_terms in entries
    for expert in (_catalog_expert(application, key, label, trigger_terms),)
    if expert.domain not in _REGISTERED_EXPERT_DOMAINS
)


def all_domain_experts() -> list[dict[str, Any]]:
    return [expert.to_dict() for expert in DOMAIN_EXPERTS]


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_+.:-]+", (text or "").lower()) if token}


def _term_hit(text: str, term: str) -> bool:
    term = (term or "").lower().strip()
    if not term:
        return False
    if " " in term or "." in term or ":" in term:
        return term in text
    return bool(re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", text))


def _infer_intent(text: str) -> str:
    if any(word in text for word in ("connect", "insert", "add node", "wire", "pin", "attribute")):
        return "graph_edit"
    if any(word in text for word in ("create", "build", "add", "setup", "make")):
        return "create_or_extend"
    if any(word in text for word in ("inspect", "find", "what", "list", "show", "report")):
        return "inspect_or_report"
    if any(word in text for word in ("fix", "repair", "validate", "compile")):
        return "repair_or_validate"
    return "general_assistance"


def _expert_brief(expert: DomainExpert) -> tuple[str, ...]:
    brief: list[str] = []
    if expert.architecture_topics:
        brief.append("architecture: " + ", ".join(expert.architecture_topics[:6]))
    if expert.implementation_approaches:
        brief.append("approaches: " + ", ".join(expert.implementation_approaches[:5]))
    if expert.tradeoffs:
        brief.append("tradeoffs: " + ", ".join(expert.tradeoffs[:4]))
    if expert.performance_concerns:
        brief.append("performance: " + ", ".join(expert.performance_concerns[:4]))
    if expert.debugging_strategies:
        brief.append("debugging: " + ", ".join(expert.debugging_strategies[:4]))
    if expert.production_concerns:
        brief.append("production: " + ", ".join(expert.production_concerns[:4]))
    if expert.refactor_strategy:
        brief.append("refactor: " + ", ".join(expert.refactor_strategy[:4]))
    if expert.senior_review_questions:
        brief.append("review: " + " | ".join(expert.senior_review_questions[:3]))
    return tuple(brief)


def _active_mode(expert: DomainExpert, settings: dict[str, Any] | None) -> str:
    settings = settings or {}
    global_mode = str(settings.get("experts.default_mode") or "").strip().lower()
    domain_mode = str(settings.get(f"experts.{expert.domain}.mode") or "").strip().lower()
    enabled = settings.get(f"experts.{expert.domain}.enabled")
    mode = domain_mode or global_mode or expert.mode
    if enabled is False:
        return "disabled"
    if enabled is True and mode == "disabled":
        return expert.mode if expert.mode != "disabled" else "observe"
    return mode if mode in EXPERT_MODES else expert.mode


def select_domain_experts(
    prompt: str,
    decision: dict[str, Any] | None = None,
    *,
    settings: dict[str, Any] | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Return structured advisory experts that match this prompt and route."""
    decision = dict(decision or {})
    text = " ".join(
        str(part or "")
        for part in (
            prompt,
            decision.get("route"),
            decision.get("execution_route"),
            decision.get("intent_category"),
            decision.get("host"),
            decision.get("target_type"),
        )
    ).lower()
    host = str(decision.get("host") or "").lower()
    route = str(decision.get("route") or "").lower()
    intent = _infer_intent(text)
    mutation = str(decision.get("mutation_scope") or "").lower()
    matches: list[ExpertMatch] = []
    token_set = _tokens(text)
    for expert in DOMAIN_EXPERTS:
        mode = _active_mode(expert, settings)
        if mode == "disabled":
            continue
        evidence: list[str] = []
        score = 0.0
        term_hits = [term for term in expert.trigger_terms if _term_hit(text, term)]
        if host and expert.application == host:
            score += 0.15
            evidence.append(f"host={host}")
        elif host and expert.application not in {host, "project", "pipeline", "python", "production", "review"}:
            score -= 0.3
        if expert.application in {"production", "review"} and term_hits:
            score += 0.25
            evidence.append("cross-cutting senior system expert")
        if expert.application == "pipeline" and ("pipeline" in route or "graph" in route):
            score += 0.35
            evidence.append(f"route={route}")
        if expert.application == "project" and route in {"project_search", "target_discovery", "project_health", "quality_audit"}:
            score += 0.35
            evidence.append(f"route={route}")
        if expert.application == "python" and (route in {"code_edit", "project_search"} or "py" in token_set):
            score += 0.25
            evidence.append("code route or Python target")
        if term_hits:
            score += min(0.5, 0.16 * len(term_hits))
            evidence.extend(f"term={term}" for term in term_hits[:4])
        if expert.domain.endswith(("node_editor", "blueprint_graph", "materials", "hypershade")) and "graph" in text:
            score += 0.1
        if mutation and mutation != "read_only":
            evidence.append(f"mutation={mutation}")
        if score < 0.25:
            continue
        expert_with_mode = DomainExpert(**{**expert.to_dict(), "mode": mode})
        matches.append(
            ExpertMatch(
                expert=expert_with_mode,
                confidence=min(0.97, max(0.35, score)),
                evidence=tuple(evidence),
                intent=intent,
                affected_elements=tuple(term_hits[:6]),
                recommended_operations=expert.capabilities[:4],
                assumptions=("Expert is advisory; execution remains owned by existing services.",),
                risks=expert.avoid[:3],
                fallbacks=("Use existing route handler if expert analysis is unavailable or low confidence.",),
                expert_brief=_expert_brief(expert_with_mode),
            )
        )
    ranked = sorted(matches, key=lambda match: (match.confidence, match.expert.mode != "observe"), reverse=True)
    return [match.to_dict() for match in ranked[:limit]]


def expert_advisory_context(
    prompt: str,
    decision: dict[str, Any] | None = None,
    *,
    settings: dict[str, Any] | None = None,
    limit: int = 4,
) -> str:
    matches = select_domain_experts(prompt, decision, settings=settings, limit=limit)
    if not matches:
        return ""
    lines = [
        "Domain expert advisory context:",
        "Experts are observation/advisory modules. Stable existing services still own execution.",
    ]
    for match in matches:
        lines.append(f"- {match['label']} [{match['domain']}; {match['mode']}; confidence={match['confidence']}]")
        if match.get("responsibilities"):
            lines.append("  responsibility: " + match["responsibilities"][0])
        if match.get("required_context"):
            lines.append("  required context: " + "; ".join(match["required_context"][:4]))
        if match.get("validation_steps"):
            lines.append("  validation: " + "; ".join(match["validation_steps"][:3]))
        if match.get("expert_brief"):
            lines.append("  senior brief: " + " | ".join(match["expert_brief"][:3]))
    return "\n".join(lines)


def expert_registry_summary() -> dict[str, Any]:
    by_app: dict[str, list[str]] = {}
    for expert in DOMAIN_EXPERTS:
        by_app.setdefault(expert.application, []).append(expert.domain)
    return {
        "framework": "modular_domain_experts_v1",
        "expert_definition": "Expert means layered senior judgment: foundation, subsystem semantics, workflow, architecture, implementation approaches, optimization, debugging, production, refactor strategy, and validation.",
        "knowledge_pyramid": list(EXPERT_KNOWLEDGE_PYRAMID),
        "expert_count": len(DOMAIN_EXPERTS),
        "applications": by_app,
        "default_modes": {expert.domain: expert.mode for expert in DOMAIN_EXPERTS},
        "execution_policy": "Experts advise and plan through existing services; they do not mutate state in observe/advise modes.",
    }
