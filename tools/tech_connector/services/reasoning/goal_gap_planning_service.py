"""Goal-driven capability gap planning.

This service is deterministic and intentionally lightweight. It does not execute
work or perform research. It turns a user goal into capability nodes, missing
links, gap resolution options, and learning recommendations so planning can account for
the real A-to-Z path instead of assuming a direct implementation step exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class CapabilityNode:
    key: str
    label: str
    status: str = "unknown"
    evidence: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "evidence": list(self.evidence),
            "requires": list(self.requires),
            "produces": list(self.produces),
            "verification": list(self.verification),
        }


@dataclass(frozen=True)
class GapResolutionOption:
    key: str
    label: str
    confidence: float
    steps: tuple[str, ...]
    pros: tuple[str, ...] = ()
    cons: tuple[str, ...] = ()
    requires_approval: bool = False
    research_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "confidence": self.confidence,
            "steps": list(self.steps),
            "pros": list(self.pros),
            "cons": list(self.cons),
            "requires_approval": self.requires_approval,
            "research_hint": self.research_hint,
        }


@dataclass(frozen=True)
class CapabilityResolutionStrategy:
    key: str
    label: str
    category: str
    confidence: float
    speed: int
    reliability: int
    maintenance: int
    requires_internet: bool = False
    requires_approval: bool = False
    requires_license_check: bool = False
    validation_required: bool = True
    pause_before_execution: bool = False
    approval_prompt: str = ""
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "confidence": self.confidence,
            "speed": self.speed,
            "reliability": self.reliability,
            "maintenance": self.maintenance,
            "requires_internet": self.requires_internet,
            "requires_approval": self.requires_approval,
            "requires_license_check": self.requires_license_check,
            "validation_required": self.validation_required,
            "pause_before_execution": self.pause_before_execution,
            "approval_prompt": self.approval_prompt,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class OperationActionType:
    key: str
    label: str
    category: str
    description: str
    host: str = ""
    requires_network: bool = False
    requires_approval: bool = False
    requires_license_check: bool = False
    report_sources: bool = False
    validates_with: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "host": self.host,
            "requires_network": self.requires_network,
            "requires_approval": self.requires_approval,
            "requires_license_check": self.requires_license_check,
            "report_sources": self.report_sources,
            "validates_with": list(self.validates_with),
        }


@dataclass(frozen=True)
class ArtifactType:
    key: str
    label: str
    category: str
    fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "fields": list(self.fields),
        }


@dataclass(frozen=True)
class CapabilityPattern:
    key: str
    labels: tuple[str, ...]
    triggers: tuple[str, ...]
    required_chain: tuple[CapabilityNode, ...]
    resolution_options: tuple[GapResolutionOption, ...]
    learning_recommendations: tuple[str, ...]
    questions: tuple[str, ...] = ()


def _uniq(values: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.append(item)
    return tuple(seen)


def _slug(text: str, fallback: str = "goal") -> str:
    value = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return value[:80] or fallback


def _function_slug(text: str, fallback: str = "operation") -> str:
    value = _slug(text, fallback=fallback)
    if value and value[0].isdigit():
        value = f"{fallback}_{value}"
    return value


def _goal_from_prompt(prompt: str) -> str:
    text = re.sub(r"\s+", " ", prompt or "").strip()
    text = re.sub(r"^(please|can you|could you|i want to|i want you to|i need to|i need you to|let'?s)\s+", "", text, flags=re.I)
    if len(text) > 140:
        text = text[:137].rstrip() + "..."
    return text or "Complete the requested objective"



def _build_problem_formulation(
    prompt: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Form the problem before capability matching or action graph creation."""
    try:
        from tech_connector.services.reasoning.problem_formulation_service import build_problem_formulation

        context = {
            "active_file": decision.get("active_file") or decision.get("current_file_path") or "",
            "open_files": list(decision.get("open_files") or []),
            "host": decision.get("host") or decision.get("execution_environment") or "",
            "conversation_entities": dict(decision.get("conversation_entities") or {}),
            "context_momentum": dict(decision.get("context_momentum") or {}),
        }
        return build_problem_formulation(
            prompt,
            decision,
            context=context,
        ).to_dict()
    except Exception as exc:
        return {
            "framework": "problem_formulation_v1",
            "literal_request": prompt,
            "interpreted_problem": _goal_from_prompt(prompt),
            "desired_outcome": _goal_from_prompt(prompt),
            "deliverables": ["answer"],
            "action_mode": "understand",
            "knowns": ["Current prompt"],
            "unknowns": [],
            "blocking_unknowns": [],
            "prerequisites": [],
            "candidate_plan": [],
            "success_conditions": ["The requested objective is completed."],
            "adequate": False,
            "can_plan": True,
            "requires_clarification": False,
            "confidence": 0.35,
            "critique": [f"Problem formulation fallback used: {exc}"],
            "meaning_graph": {"framework": "meaning_graph_v1", "nodes": [], "edges": []},
        }


def _capability_nodes_from_problem_formulation(
    formulation: dict[str, Any],
) -> list[CapabilityNode]:
    """Translate meaning prerequisites into planner nodes without losing semantics."""
    nodes: list[CapabilityNode] = []
    for index, step in enumerate(list(formulation.get("candidate_plan") or []), start=1):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("step_id") or f"formulation_step_{index}")
        objective = str(step.get("objective") or step_id)
        action = str(step.get("action") or "")
        status = "missing_or_unverified"
        if action in {"report"}:
            status = "blocked_by_prerequisites"
        nodes.append(
            CapabilityNode(
                key=f"problem.{_slug(step_id)}",
                label=objective,
                status=status,
                evidence=("problem formulation",),
                requires=tuple(str(value) for value in step.get("depends_on") or []),
                produces=tuple(str(value) for value in step.get("produces") or []),
                verification=tuple(
                    [str(step.get("success_condition") or "Step result satisfies the formulated problem.")]
                ),
            )
        )
    return nodes


def _problem_formulation_requires_pause(formulation: dict[str, Any]) -> bool:
    return bool(
        formulation.get("requires_clarification")
        or not formulation.get("can_plan", True)
    )

def _terms(text: str) -> set[str]:
    lower = (text or "").lower()
    return set(re.findall(r"[a-z0-9_]+", lower))


def _node(
    key: str,
    label: str,
    *,
    requires: tuple[str, ...] = (),
    produces: tuple[str, ...] = (),
    verification: tuple[str, ...] = (),
) -> CapabilityNode:
    return CapabilityNode(
        key=key,
        label=label,
        requires=requires,
        produces=produces,
        verification=verification,
    )


RESOLUTION_STRATEGIES: tuple[CapabilityResolutionStrategy, ...] = (
    CapabilityResolutionStrategy(
        key="internal_function",
        label="Use internal function",
        category="internal",
        confidence=0.96,
        speed=5,
        reliability=5,
        maintenance=5,
        validation_required=True,
        notes=("Prefer when the function is indexed, callable, and matches the required capability.",),
    ),
    CapabilityResolutionStrategy(
        key="internal_workflow",
        label="Use existing workflow",
        category="internal",
        confidence=0.9,
        speed=5,
        reliability=4,
        maintenance=5,
        notes=("Prefer when a saved pipeline already matches the desired capability.",),
    ),
    CapabilityResolutionStrategy(
        key="compose_internal_functions",
        label="Compose multiple internal functions",
        category="internal",
        confidence=0.84,
        speed=4,
        reliability=4,
        maintenance=4,
        notes=("Use when no single function exists but compatible internal operations can produce the capability.",),
    ),
    CapabilityResolutionStrategy(
        key="project_index_search",
        label="Search existing project/index",
        category="local_discovery",
        confidence=0.8,
        speed=4,
        reliability=4,
        maintenance=4,
        notes=("Use local symbols, docs, workflows, host metadata, and project files before external lookup.",),
    ),
    CapabilityResolutionStrategy(
        key="local_documentation",
        label="Search local documentation",
        category="local_discovery",
        confidence=0.76,
        speed=4,
        reliability=4,
        maintenance=4,
        notes=("Use when indexed code is incomplete but local docs/playbooks may define the technique.",),
    ),
    CapabilityResolutionStrategy(
        key="official_documentation",
        label="Search official documentation",
        category="research",
        confidence=0.82,
        speed=3,
        reliability=5,
        maintenance=4,
        requires_internet=True,
        pause_before_execution=False,
        approval_prompt="After research, report official/source links found, version relevance, why each source fit, and what guidance was added or used.",
        notes=("Use for version-specific APIs, DCC/engine features, or high-risk unfamiliar operations.",),
    ),
    CapabilityResolutionStrategy(
        key="github_ingest",
        label="Search GitHub and ingest candidate",
        category="acquisition",
        confidence=0.64,
        speed=2,
        reliability=2,
        maintenance=2,
        requires_internet=True,
        requires_approval=True,
        requires_license_check=True,
        pause_before_execution=True,
        approval_prompt="Show candidate repository links, license notes, fit rationale, risks, and exact ingest plan before proceeding.",
        notes=("Use only when internal/project/official sources are insufficient and the user approves ingestion.",),
    ),
    CapabilityResolutionStrategy(
        key="plugin_marketplace",
        label="Search installed/plugin marketplace",
        category="acquisition",
        confidence=0.68,
        speed=2,
        reliability=3,
        maintenance=3,
        requires_internet=True,
        requires_approval=True,
        requires_license_check=True,
        pause_before_execution=True,
        approval_prompt="Show plugin/source link, license/commercial terms, fit rationale, install/ingest impact, and rollback path before proceeding.",
        notes=("Use when a known app/plugin capability is likely to solve the missing requirement.",),
    ),
    CapabilityResolutionStrategy(
        key="asset_source_search",
        label="Search animation/asset providers",
        category="asset_acquisition",
        confidence=0.79,
        speed=2,
        reliability=4,
        maintenance=3,
        requires_internet=True,
        requires_approval=True,
        requires_license_check=True,
        pause_before_execution=True,
        approval_prompt="Show asset/provider links, license terms, skeleton/format fit, and the intended import path before download.",
        notes=("Use for providers such as Mixamo, ActorCore, Rokoko, Fab, or other animation/asset libraries.",),
    ),
    CapabilityResolutionStrategy(
        key="ai_animation_service",
        label="Search text/video-to-animation services",
        category="ai_service",
        confidence=0.62,
        speed=2,
        reliability=2,
        maintenance=2,
        requires_internet=True,
        requires_approval=True,
        requires_license_check=True,
        pause_before_execution=True,
        approval_prompt="Show service links, upload/privacy implications, terms, expected output format, and validation plan before use.",
        notes=("Use when the prompt asks to create animation from text, video, or mocap-like source media.",),
    ),
    CapabilityResolutionStrategy(
        key="generate_new_code",
        label="Generate new code or wrapper",
        category="generation",
        confidence=0.7,
        speed=3,
        reliability=3,
        maintenance=3,
        requires_approval=True,
        validation_required=True,
        notes=("Use after signatures/APIs are verified; compile/test before registering as reusable.",),
    ),
    CapabilityResolutionStrategy(
        key="ask_user",
        label="Ask user for missing context or approval",
        category="human",
        confidence=0.95,
        speed=1,
        reliability=5,
        maintenance=5,
        requires_approval=True,
        validation_required=False,
        notes=("Use when multiple plausible targets or acquisition choices would alter user data differently.",),
    ),
)


ACTION_TYPES: tuple[OperationActionType, ...] = (
    OperationActionType(
        key="execute_internal_function",
        label="Execute internal function",
        category="internal",
        description="Run a registered/indexed internal function or tool operation.",
        validates_with=("function result", "changed state query", "unit or smoke test"),
    ),
    OperationActionType(
        key="run_python_function",
        label="Run basic Python function",
        category="local_code",
        description="Run a small verified Python helper, script, or generated wrapper in the local runtime.",
        validates_with=("return value", "py_compile", "focused smoke test"),
    ),
    OperationActionType(
        key="code.search_project",
        label="Search project files",
        category="local_code",
        description="Search project files, tests, symbols, and docs for the concrete targets implied by a coding prompt.",
        validates_with=("matching files are listed", "search terms and exclusions are recorded", "target ownership is explicit"),
    ),
    OperationActionType(
        key="code.inspect_symbols",
        label="Inspect code symbols and call sites",
        category="local_code",
        description="Inspect functions/classes/callers/tests before editing.",
        validates_with=("symbols and call sites are read", "current behavior is summarized", "affected tests are identified"),
    ),
    OperationActionType(
        key="code.plan_patch",
        label="Plan concrete code patch",
        category="local_code",
        description="Turn the prompt and inspected code into scoped file edits with rollback and validation expectations.",
        validates_with=("target files are explicit", "edit intent is mapped to tests", "risk/rollback note exists"),
    ),
    OperationActionType(
        key="code.plan_expected_code",
        label="Plan expected code artifact",
        category="local_code",
        description="Describe the exact expected files, classes, methods, signals, and representative code skeleton before patching.",
        validates_with=("expected files are explicit", "classes and integration points are named", "code skeleton maps to existing services"),
    ),
    OperationActionType(
        key="code.validate_expected_code",
        label="Validate expected code artifact",
        category="local_code",
        description="Run static checks and optional disposable smoke tests against the generated code artifact before patching.",
        validates_with=("representative code parses", "expected classes are present", "method contracts and quality gates exist", "mock smoke test passes when available"),
    ),
    OperationActionType(
        key="code.validate_patch_in_temp_workspace",
        label="Validate patch in temp workspace",
        category="local_code",
        description="Apply or materialize generated patch files in a disposable workspace and run focused validation there before touching the live project.",
        validates_with=("temp workspace is created", "generated files compile", "focused commands exit cleanly", "live project files remain untouched"),
    ),
    OperationActionType(
        key="code.apply_patch",
        label="Apply scoped code patch",
        category="local_code",
        description="Apply source edits through a patch operation and avoid unrelated changes.",
        validates_with=("patch applies cleanly", "changed files match intended targets", "no unrelated files are modified"),
    ),
    OperationActionType(
        key="code.update_tests",
        label="Update focused tests",
        category="local_code",
        description="Add or update focused regression tests that prove the requested behavior.",
        validates_with=("tests encode requested behavior", "negative/edge case is covered when relevant", "test file path is recorded"),
    ),
    OperationActionType(
        key="code.run_tests",
        label="Run focused code validation",
        category="local_code",
        description="Run compile, unit, smoke, or static validation for the changed code.",
        validates_with=("command exit code is captured", "failures are summarized", "remaining risk is explicit"),
    ),
    OperationActionType(
        key="run_dcc_operation",
        label="Run DCC host operation",
        category="dcc",
        description="Run a registered host operation through Maya, Blender, Unreal, Houdini, MotionBuilder, Substance, or Unity context.",
        validates_with=("host query", "asset/scene state inspection", "operation result"),
    ),
    OperationActionType(
        key="web_knowledge_search",
        label="Search web/official knowledge",
        category="research",
        description="Find current official or authoritative technique/API guidance and report links/relevance afterward.",
        requires_network=True,
        report_sources=True,
        validates_with=("source relevance summary", "version/API compatibility check"),
    ),
    OperationActionType(
        key="github_candidate_review",
        label="Review GitHub candidate",
        category="acquisition",
        description="Find candidate repositories, then pause with link, fit rationale, license notes, and ingest plan.",
        requires_network=True,
        requires_approval=True,
        requires_license_check=True,
        report_sources=True,
        validates_with=("user approval", "license check", "repo fit summary"),
    ),
    OperationActionType(
        key="plugin_candidate_review",
        label="Review plugin candidate",
        category="acquisition",
        description="Find candidate installed/marketplace plugin and pause with fit, license, install, and rollback notes.",
        requires_network=True,
        requires_approval=True,
        requires_license_check=True,
        report_sources=True,
        validates_with=("user approval", "plugin compatibility check"),
    ),
    OperationActionType(
        key="download_or_ingest_asset",
        label="Download or ingest asset",
        category="asset_acquisition",
        description="Acquire an external asset such as animation, model, texture, or data after approval/license checks when required.",
        requires_network=True,
        requires_approval=True,
        requires_license_check=True,
        report_sources=True,
        validates_with=("file exists", "license/source logged", "asset format check"),
    ),
    OperationActionType(
        key="import_unreal_asset",
        label="Import asset into Unreal",
        category="engine_import",
        description="Import acquired or generated assets into Unreal and verify the imported asset path.",
        host="unreal",
        validates_with=("asset exists in Content Browser", "import log", "asset load/compile check"),
    ),
    OperationActionType(
        key="blueprint.scan",
        label="Scan Blueprint or AnimBlueprint graph",
        category="unreal_blueprint",
        description="Read Blueprint/AnimBlueprint graphs, variables, functions, and compile state before mutation.",
        host="unreal",
        validates_with=("asset loads", "graphs/variables are read back", "target node/state path is identified"),
    ),
    OperationActionType(
        key="anim_graph.add_state",
        label="Add AnimGraph state",
        category="unreal_anim_graph",
        description="Create a concrete state in an AnimBlueprint state machine.",
        host="unreal",
        validates_with=("state exists after readback", "state name is unique", "owning state machine is unchanged except intended additions"),
    ),
    OperationActionType(
        key="anim_graph.add_transition_rule",
        label="Add AnimGraph transition rule",
        category="unreal_anim_graph",
        description="Create and synthesize transition rule graph logic between AnimBlueprint states.",
        host="unreal",
        validates_with=("transition exists after readback", "rule graph contains required predicates", "compile succeeds"),
    ),
    OperationActionType(
        key="anim_graph.wire_state_machine_to_output_pose",
        label="Wire state machine to output pose",
        category="unreal_anim_graph",
        description="Wire an AnimGraph state machine or pose path to the final output pose.",
        host="unreal",
        validates_with=("output pose path is connected", "graph readback confirms pins", "compile succeeds"),
    ),
    OperationActionType(
        key="blueprint.compile_and_save",
        label="Compile and save Blueprint",
        category="unreal_blueprint",
        description="Compile, save, and reload a Blueprint or AnimBlueprint asset.",
        host="unreal",
        validates_with=("compile status is success", "asset save succeeds", "reload/readback succeeds"),
    ),
    OperationActionType(
        key="niagara.create_emitter",
        label="Create Niagara emitter",
        category="unreal_niagara",
        description="Create or duplicate a Niagara emitter asset with requested parameters.",
        host="unreal",
        validates_with=("emitter asset exists", "asset class is NiagaraEmitter", "configured properties read back"),
    ),
    OperationActionType(
        key="blueprint.add_event",
        label="Add Blueprint event/function wiring",
        category="unreal_blueprint",
        description="Add Blueprint events, functions, or graph nodes needed for gameplay behavior.",
        host="unreal",
        validates_with=("event/function exists", "pins are connected", "compile succeeds"),
    ),
    OperationActionType(
        key="blueprint.attach_to_socket",
        label="Attach component or FX to socket",
        category="unreal_blueprint",
        description="Attach a component, Niagara system, or spawned effect to a named skeletal mesh socket.",
        host="unreal",
        validates_with=("socket exists", "attachment target resolves", "runtime spawn/attach path is callable"),
    ),
    OperationActionType(
        key="unreal.create_validation_map",
        label="Create disposable Unreal validation map",
        category="unreal_validation",
        description="Create or use a disposable validation level/map to prove the feature without touching production maps.",
        host="unreal",
        validates_with=("map opens", "test actors spawn", "proof artifacts are recorded"),
    ),
    OperationActionType(
        key="blender.clean_animation",
        label="Clean Blender animation",
        category="blender_animation",
        description="Clean, normalize, and prepare animation curves or armature data in Blender.",
        host="blender",
        validates_with=("source action exists", "curve/keyframe cleanup readback", "frame range and root motion are explicit"),
    ),
    OperationActionType(
        key="blender.scan_animation",
        label="Scan Blender animation",
        category="blender_animation",
        description="Inspect Blender armature/action, frame range, root motion, scale, and selected objects before cleanup/export.",
        host="blender",
        validates_with=("armature/action readback succeeds", "frame range is captured", "selected objects are listed"),
    ),
    OperationActionType(
        key="blender.export_fbx",
        label="Export Blender FBX",
        category="blender_export",
        description="Export a validated Blender animation or rig selection to FBX for Unreal import.",
        host="blender",
        validates_with=("FBX file exists", "export settings recorded", "skeleton/scale axes are checked"),
    ),
    OperationActionType(
        key="blender.scan_scene_selection",
        label="Scan Blender selected scene objects",
        category="blender_mesh",
        description="Inspect selected Blender mesh objects, names, transforms, materials, and LOD candidates.",
        host="blender",
        validates_with=("selected mesh readback succeeds", "transform/material/LOD facts are captured"),
    ),
    OperationActionType(
        key="blender.clean_meshes",
        label="Clean Blender mesh objects",
        category="blender_mesh",
        description="Apply transforms, normalize names/origins/scale, and prepare LOD mesh objects for export.",
        host="blender",
        validates_with=("names/transforms/LOD objects read back", "dry-run or change report is captured"),
    ),
    OperationActionType(
        key="unreal.import_static_mesh_fbx",
        label="Import Unreal static mesh FBX",
        category="unreal_static_mesh",
        description="Import a Blender FBX as Unreal static mesh assets in the requested content path.",
        host="unreal",
        validates_with=("static mesh assets exist", "import result paths are recorded"),
    ),
    OperationActionType(
        key="unreal.configure_static_mesh",
        label="Configure Unreal static mesh",
        category="unreal_static_mesh",
        description="Configure LODs, material slots, collision, and save static mesh assets.",
        host="unreal",
        validates_with=("LOD/material/collision readback succeeds", "asset save result is captured"),
    ),
    OperationActionType(
        key="unreal.retarget_animation",
        label="Retarget animation in Unreal",
        category="unreal_animation",
        description="Retarget an imported animation clip onto the requested Unreal skeleton.",
        host="unreal",
        validates_with=("target animation asset exists", "target skeleton matches", "preview/readback succeeds"),
    ),
    OperationActionType(
        key="unreal.create_blendspace",
        label="Create or update Unreal BlendSpace",
        category="unreal_animation",
        description="Create or update a BlendSpace and add the relevant animation samples.",
        host="unreal",
        validates_with=("BlendSpace asset exists", "samples are assigned", "axis/settings read back"),
    ),
    OperationActionType(
        key="maya.adjust_facial_control_rig",
        label="Adjust Maya facial control rig",
        category="maya_rigging",
        description="Apply facial control rig adjustments or keys in Maya for a target expression.",
        host="maya",
        validates_with=("controls resolve", "keys/values are read back", "scene remains valid"),
    ),
    OperationActionType(
        key="maya.scan_facial_rig",
        label="Scan Maya facial rig",
        category="maya_rigging",
        description="Inspect Maya facial controls, current selection, animation range, and export readiness.",
        host="maya",
        validates_with=("facial controls are listed", "selection/readback succeeds", "frame range is captured"),
    ),
    OperationActionType(
        key="metahuman.propagate_dna",
        label="Propagate MetaHuman DNA changes",
        category="metahuman_pipeline",
        description="Use MetaHumanDNA tooling when available to propagate expression or rig deltas.",
        validates_with=("MetaHumanDNA tool path resolves", "DNA output/provenance is recorded", "compatibility check passes"),
    ),
    OperationActionType(
        key="unreal.hook_facial_animbp_slot",
        label="Hook facial AnimBP slot",
        category="unreal_animation",
        description="Connect imported facial animation to the requested facial AnimBlueprint slot.",
        host="unreal",
        validates_with=("slot/node exists", "asset is assigned", "compile succeeds"),
    ),
    OperationActionType(
        key="sequencer.validate_playback",
        label="Validate Sequencer playback",
        category="unreal_validation",
        description="Open or create a Sequencer validation shot and prove playback for the imported animation.",
        host="unreal",
        validates_with=("sequence opens", "animation track plays", "playback proof is recorded"),
    ),
    OperationActionType(
        key="generate_code_or_wrapper",
        label="Generate code or wrapper",
        category="generation",
        description="Create a narrow helper/wrapper after APIs are verified, then validate before use.",
        requires_approval=True,
        validates_with=("compile", "tests", "registered callable metadata"),
    ),
    OperationActionType(
        key="register_capability",
        label="Register reusable capability",
        category="learning",
        description="Save validated capability metadata so future plans can use it as an internal option.",
        validates_with=("capability registry entry", "index refresh", "future lookup"),
    ),
    OperationActionType(
        key="validate_result",
        label="Validate result",
        category="validation",
        description="Run the smallest practical validation for the modified file, asset, graph, scene, or workflow.",
        validates_with=("validation evidence", "warnings", "rollback decision if invalid"),
    ),
)


ARTIFACT_TYPES: tuple[ArtifactType, ...] = (
    ArtifactType("file", "File", "filesystem", ("path", "format", "checksum")),
    ArtifactType("directory", "Directory", "filesystem", ("path",)),
    ArtifactType("source_code", "SourceCode", "code", ("language", "path", "symbols")),
    ArtifactType("executable_function", "ExecutableFunction", "code", ("name", "signature", "provider_id")),
    ArtifactType("plugin", "Plugin", "extension", ("name", "version", "provider", "license")),
    ArtifactType("repository", "Repository", "external_source", ("url", "owner", "commit", "license")),
    ArtifactType("documentation", "Documentation", "knowledge", ("url", "title", "version", "relevance")),
    ArtifactType("animation_clip", "AnimationClip", "dcc_asset", ("format", "frame_rate", "duration", "source_skeleton", "root_motion", "license", "coordinate_system")),
    ArtifactType("skeleton", "Skeleton", "dcc_asset", ("joint_hierarchy", "coordinate_system", "scale", "source_host")),
    ArtifactType("skeletal_mesh", "SkeletalMesh", "dcc_asset", ("mesh", "skeleton", "materials", "bind_info")),
    ArtifactType("texture", "Texture", "dcc_asset", ("format", "resolution", "color_space", "license")),
    ArtifactType("material", "Material", "dcc_asset", ("shader_model", "textures", "parameters")),
    ArtifactType("unreal_asset", "UnrealAsset", "engine_asset", ("object_path", "asset_class", "package_path")),
    ArtifactType("blender_object", "BlenderObject", "dcc_state", ("object_name", "object_type", "scene")),
    ArtifactType("maya_node", "MayaNode", "dcc_state", ("node_name", "node_type", "scene")),
    ArtifactType("workflow", "Workflow", "pipeline", ("steps", "inputs", "outputs")),
    ArtifactType("validation_report", "ValidationReport", "evidence", ("status", "checks", "warnings", "errors")),
    ArtifactType("license_record", "LicenseRecord", "provenance", ("source_url", "license", "review_status")),
    ArtifactType("credential_reference", "CredentialReference", "security", ("provider", "scope", "storage_key")),
    ArtifactType("execution_result", "ExecutionResult", "evidence", ("status", "stdout", "stderr", "artifacts")),
    ArtifactType("compatibility_report", "CompatibilityReport", "analysis", ("source", "target", "issues", "conversion_plan")),
    ArtifactType("asset_candidate_list", "AssetCandidateList", "candidate_set", ("provider", "query", "candidates", "ranking")),
    ArtifactType("provenance_record", "ProvenanceRecord", "provenance", ("source_url", "provider", "date", "checksum", "trust_state")),
)


PATTERNS: tuple[CapabilityPattern, ...] = (
    CapabilityPattern(
        key="unreal.motion_matching",
        labels=("Motion matching animation feature",),
        triggers=("motion matching", "pose search", "locomotion database", "chooser", "climbing"),
        required_chain=(
            _node("existing_climbing_system", "Existing climbing or traversal system", produces=("movement states",), verification=("identify current climbing assets/classes/graphs",)),
            _node("compatible_skeleton", "Compatible character skeleton and animation blueprint", requires=("target character",), produces=("retarget target",), verification=("verify skeleton, mesh, and AnimBP paths",)),
            _node("pose_search_or_plugin", "Pose Search / Motion Matching plugin capability", requires=("unreal version",), produces=("runtime query support",), verification=("verify plugin availability and enabled state",)),
            _node("animation_database", "Animation database or pose-search schema", requires=("compatible animations", "pose search capability"), produces=("queryable animation set",), verification=("compile/load database asset",)),
            _node("animation_metadata", "Animation metadata, tags, sync markers, or trajectory features", requires=("animation set",), produces=("search features",), verification=("inspect tags/features on candidate clips",)),
            _node("runtime_integration", "Runtime integration from climbing state into motion matching query", requires=("movement state", "database", "AnimGraph insertion point"), produces=("playable integrated feature",), verification=("preview AnimGraph path and test state transition",)),
        ),
        resolution_options=(
            GapResolutionOption(
                key="official_pose_search",
                label="Use Unreal Pose Search / Motion Matching where available",
                confidence=0.9,
                steps=("verify plugin and engine version", "build/search database", "connect existing climbing state", "validate AnimGraph transition"),
                pros=("highest alignment with current Unreal architecture", "less custom runtime code"),
                cons=("requires compatible engine/plugin support and animation data",),
                research_hint="Official Unreal Pose Search / Motion Matching documentation",
            ),
            GapResolutionOption(
                key="simplified_state_machine_resolution",
                label="Build a staged climbing state-machine integration first",
                confidence=0.72,
                steps=("reuse current climbing state", "add metadata-driven clip selection", "defer full pose search until data exists"),
                pros=("testable without a full database", "preserves existing behavior"),
                cons=("not full motion matching",),
            ),
            GapResolutionOption(
                key="custom_runtime",
                label="Create a custom runtime matcher",
                confidence=0.45,
                steps=("define feature vectors", "sample animation poses", "build runtime query", "validate performance"),
                pros=("maximum control",),
                cons=("high risk and likely unnecessary if built-in tools exist",),
                requires_approval=True,
                research_hint="Research papers and production examples for pose matching",
            ),
        ),
        learning_recommendations=(
            "Create a reusable Unreal locomotion/motion-matching capability pack after the first validated implementation.",
            "Persist animation database/tagging requirements as project-local knowledge.",
            "Add a gap-resolution recipe for climbing state to AnimGraph motion-selection insertion points.",
        ),
        questions=("Which character skeleton/AnimBP should receive the feature if multiple are found?",),
    ),
    CapabilityPattern(
        key="unreal.character_stamina",
        labels=("Reusable character stamina system",),
        triggers=("stamina", "energy", "sprint", "recovery rate", "drain rate"),
        required_chain=(
            _node("existing_movement_system", "Existing sprint/movement-state implementation", produces=("integration point",), verification=("find sprint input, movement component, Blueprint/C++/GAS path",)),
            _node("stat_architecture", "Existing stat/component/GAS architecture", requires=("project scan",), produces=("preferred storage location",), verification=("identify reusable component/attribute system",)),
            _node("stamina_contract", "Stamina data and events contract", requires=("max/drain/recovery requirements",), produces=("public UI/read events",), verification=("check callbacks/replication semantics",)),
            _node("sprint_integration", "Integration with current sprint path", requires=("integration point", "stamina contract"), produces=("single sprint path",), verification=("drain/cancel/recover behavior checks",)),
            _node("network_policy", "Replication/authority policy if networked", requires=("networked project detection",), produces=("minimal replicated state",), verification=("server authority and UI read path verified",)),
        ),
        resolution_options=(
            GapResolutionOption(
                key="reuse_existing_stat_system",
                label="Extend existing stat/GAS/component architecture",
                confidence=0.88,
                steps=("inspect existing systems", "extend matching component/attribute", "wire current sprint path", "validate thresholds and events"),
                pros=("lowest duplication", "fits project conventions"),
                cons=("requires accurate discovery before editing",),
            ),
            GapResolutionOption(
                key="new_component_resolution",
                label="Create a reusable stamina component and adapt sprint to it",
                confidence=0.72,
                steps=("create component", "add events/read API", "connect existing sprint", "validate movement-only drain"),
                pros=("portable and clear",),
                cons=("must avoid parallel sprint logic",),
            ),
        ),
        learning_recommendations=(
            "Save a reusable character-stat planning playbook after implementation.",
            "Index detected sprint integration points for future movement-system prompts.",
        ),
        questions=("If multiple playable character classes exist, confirm the primary target before mutation.",),
    ),
    CapabilityPattern(
        key="code.docstrings",
        labels=("Code documentation/docstring completion",),
        triggers=("docstring", "docstrings", "missing params", "document functions", "add docs"),
        required_chain=(
            _node("symbol_inventory", "Function/class inventory", produces=("functions missing docstrings", "functions with incomplete params"), verification=("parse AST and signatures",)),
            _node("style_contract", "Project docstring style contract", requires=("examples or existing conventions",), produces=("format rules",), verification=("compare with existing docstrings",)),
            _node("safe_doc_update", "Doc-only update path", requires=("symbol inventory", "style contract"), produces=("updated docstrings",), verification=("syntax check modified files",)),
        ),
        resolution_options=(
            GapResolutionOption(
                key="ast_docstring_patch",
                label="Use AST-backed docstring patching",
                confidence=0.86,
                steps=("find missing/incomplete docstrings", "generate style-matched docs", "patch only docstrings", "run py_compile"),
                pros=("low behavioral risk", "can prioritize missing params"),
                cons=("semantic descriptions still need project context",),
            ),
        ),
        learning_recommendations=(
            "Persist the detected docstring style as a project documentation profile.",
            "Add a reusable docstring-completion pipeline node.",
        ),
    ),
    CapabilityPattern(
        key="code.multi_file_implementation",
        labels=("Concrete multi-file code implementation workflow",),
        triggers=("multi-file", "rollback journal", "failed write", "refactor", "prompt router", "fuzz regression", "attribution paths", "service tests", "update the service tests"),
        required_chain=(
            _node("code_target_scan", "Search project files, tests, routes, services, and docs for concrete edit targets", requires=("project root", "prompt terms"), produces=("candidate files", "existing patterns"), verification=("code.search_project returns file paths and matched terms")),
            _node("code_symbol_inspection", "Inspect target symbols, call sites, contracts, and existing tests", requires=("candidate files",), produces=("symbol/call graph context", "test targets"), verification=("code.inspect_symbols captures relevant definitions and callers")),
            _node("code_change_design", "Design scoped file edits and rollback/compatibility strategy", requires=("symbol/call graph context", "requested behavior"), produces=("patch plan", "validation commands"), verification=("code.plan_patch maps each behavior to files and tests")),
            _node("code_expected_artifact", "Produce expected files, imports, classes, methods, integration points, and representative code before patching", requires=("patch plan", "symbol/call graph context"), produces=("planned code artifact"), verification=("code.plan_expected_code includes concrete implementation shape and representative code")),
            _node("code_expected_artifact_validation", "Validate the expected code artifact with static checks and disposable smoke tests before patching", requires=("planned code artifact",), produces=("code artifact validation report"), verification=("code.validate_expected_code confirms parsing, expected classes, contracts, gates, and smoke fixture when available")),
            _node("code_temp_workspace_validation", "Materialize the generated patch in a disposable workspace and run focused validation before touching live files", requires=("planned code artifact", "code artifact validation report"), produces=("temp workspace validation report"), verification=("code.validate_patch_in_temp_workspace returns commands, exit codes, written files, and untouched-live-tree evidence")),
            _node("code_patch_application", "Apply the implementation patch without unrelated changes", requires=("patch plan", "temp workspace validation report"), produces=("modified source files"), verification=("code.apply_patch applies cleanly and changed paths match plan")),
            _node("code_test_update", "Add or update focused regression tests for the requested behavior", requires=("patch plan", "test targets"), produces=("modified test files"), verification=("code.update_tests proves requested behavior and edge case")),
            _node("code_validation_report", "Run focused compile/tests and report remaining gaps", requires=("modified source files", "modified test files"), produces=("validation evidence", "final report"), verification=("code.run_tests captures commands, exit codes, and failures")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="inspect_patch_test_report",
                label="Search, inspect, patch, test, and report with explicit changed files",
                confidence=0.86,
                steps=("code.search_project", "code.inspect_symbols", "code.plan_patch", "code.plan_expected_code", "code.validate_expected_code", "code.validate_patch_in_temp_workspace", "code.apply_patch", "code.update_tests", "code.run_tests"),
                pros=("keeps implementation grounded in real files", "makes validation and rollback explicit"),
                cons=("requires project index/search quality before editing",),
            ),
        ),
        learning_recommendations=(
            "Save successful search terms, target files, and validation commands as reusable prompt-system implementation knowledge.",
            "Promote useful prompt mutations or planner edge cases into deterministic regression fixtures.",
        ),
    ),
    CapabilityPattern(
        key="code.qt_operation_runner_ui",
        labels=("Qt operation runner UI for registered functions",),
        triggers=("qt", "pyside", "tool panel", "operation catalog", "registered unreal/dcc operation", "edit its arguments as json", "without blocking the ui", "result/progress/errors"),
        required_chain=(
            _node("qt_ui_pattern_scan", "Inspect existing PySide/Qt widgets, worker-thread patterns, and app tab integration points", requires=("project root", "Qt prompt"), produces=("Qt style conventions", "integration location"), verification=("code.search_project finds QWidget/QThread/QPlainTextEdit/QTableWidget patterns")),
            _node("operation_catalog_scan", "Inspect Unreal and DCC operation catalog APIs and payload builders", requires=("operation catalog requirement"), produces=("catalog function contracts", "dispatch payload shape"), verification=("code.inspect_symbols confirms operation_catalog, dcc_operation_registry, unreal_operation_payload, and execution service entry points")),
            _node("qt_operation_ui_design", "Design OperationRunnerPanel with catalog search, operation table, JSON argument editor, run/queue button, and result/progress output", requires=("Qt style conventions", "catalog function contracts"), produces=("widget class design", "worker class design", "signal contract"), verification=("code.plan_patch maps UI controls, signals, worker, dispatch, and validation")),
            _node("qt_expected_code_artifact", "Produce expected code skeleton for the Qt panel, worker, catalog loading, dispatch boundary, and app integration", requires=("widget class design", "worker class design"), produces=("planned code artifact"), verification=("code.plan_expected_code includes files, classes, methods, signals, imports, and representative code")),
            _node("qt_expected_code_validation", "Run static checks and a disposable mocked smoke test against the generated Qt artifact before patching", requires=("planned code artifact",), produces=("Qt artifact validation report"), verification=("code.validate_expected_code parses classes, checks contracts, and runs mocked worker/catalog smoke path")),
            _node("qt_temp_workspace_validation", "Materialize the Qt panel patch in a temp workspace and compile/run focused validation before live project edits", requires=("planned code artifact", "Qt artifact validation report"), produces=("temp workspace validation report"), verification=("code.validate_patch_in_temp_workspace compiles generated panel/test files outside the live tree")),
            _node("qt_operation_ui_patch", "Apply the Qt operation runner UI implementation and app integration", requires=("planned code artifact", "temp workspace validation report"), produces=("new/modified Qt files"), verification=("code.apply_patch changes only expected UI/app/test files")),
            _node("qt_operation_ui_tests", "Add focused tests for catalog loading, JSON argument templating, and non-blocking worker dispatch", requires=("new/modified Qt files"), produces=("Qt/service tests"), verification=("code.update_tests proves catalog entries and queued execution payloads")),
            _node("qt_operation_ui_validation", "Run compile and focused tests for the Qt operation runner UI", requires=("Qt/service tests"), produces=("validation evidence"), verification=("code.run_tests captures py_compile and focused unittest results")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="qt_widget_worker_catalog_dispatch",
                label="Build a PySide QWidget with QThread worker and registered catalog dispatch",
                confidence=0.9,
                steps=("code.search_project", "code.inspect_symbols", "code.plan_patch", "code.plan_expected_code", "code.validate_expected_code", "code.validate_patch_in_temp_workspace", "code.apply_patch", "code.update_tests", "code.run_tests"),
                pros=("matches existing PySide patterns", "keeps execution non-blocking", "uses registered Unreal/DCC catalog APIs"),
                cons=("live host execution still depends on host connection status and dispatch adapters"),
            ),
        ),
        learning_recommendations=(
            "Save Qt operation-runner UI as a reusable code-generation pattern for tool panels.",
            "Promote catalog/worker/JSON-editor expectations into planner regression fixtures.",
        ),
    ),
    CapabilityPattern(
        key="external.asset_acquisition",
        labels=("External asset acquisition and import",),
        triggers=("mesh", "model", "3d asset", "asset online", "download asset", "find asset", "texture", "material", "import asset", "text to mesh", "image to mesh"),
        required_chain=(
            _node("asset_requirements", "Asset requirements and constraints", produces=("asset query", "format constraints", "license constraints"), verification=("asset type, target host, and license needs are explicit",)),
            _node("external_asset_source", "External asset/marketplace/source candidate", requires=("asset query", "license constraints"), produces=("asset candidate list",), verification=("source link, preview/relevance, license, and format are recorded",)),
            _node("asset_ingest", "Asset download/ingest", requires=("approved source",), produces=("local asset file"), verification=("file exists and format is supported",)),
            _node("asset_import_or_conversion", "Asset import or conversion", requires=("local asset file", "target host/project"), produces=("imported or converted asset"), verification=("asset loads in target host and required materials/textures resolve",)),
        ),
        resolution_options=(
            GapResolutionOption(
                key="review_provider_then_import",
                label="Review marketplace/source candidates, then import the selected asset",
                confidence=0.78,
                steps=("collect provider candidates", "show links/preview/license/fit", "pause for user selection", "download or ingest selected asset", "import/convert and validate"),
                pros=("keeps provider choice visible", "works for meshes, models, textures, materials, and tools"),
                cons=("depends on provider availability and license/format compatibility",),
                requires_approval=True,
            ),
        ),
        learning_recommendations=(
            "Save validated asset source/import mappings as reusable provider knowledge.",
            "Register successful asset conversion/import steps as reusable pipeline nodes.",
        ),
        questions=("Which target host/project folder should receive the asset if it is not explicit?",),
    ),
    CapabilityPattern(
        key="unreal.anim_blueprint_locomotion_crawl",
        labels=("Unreal AnimBlueprint locomotion crawl feature",),
        triggers=("abp_locomotion", "abp_combat", "crouch-crawl", "crawl", "state machine", "transition rule", "output pose", "aim offset"),
        required_chain=(
            _node("abp_target_scan", "Scan ABP_Locomotion and ABP_Combat graphs, variables, state machines, and compile state", requires=("target AnimBlueprint paths",), produces=("graph inventory", "state machine insertion points"), verification=("blueprint.scan returns graphs/states/variables", "compile status is captured before mutation")),
            _node("crawl_variable_contract", "Add or reuse crawl/rifle locomotion variables and gameplay input contract", requires=("graph inventory", "movement input source"), produces=("variable contract", "transition predicates"), verification=("variables exist and are not duplicated", "input/weapon conditions are explicit")),
            _node("crawl_state_creation", "Add crouch-crawl state and animation player/blend asset reference", requires=("state machine insertion point", "crawl animation asset or placeholder"), produces=("crawl state"), verification=("anim_graph.add_state readback confirms state")),
            _node("crawl_transition_rules", "Add enter/exit transition rule graph logic for crouch, rifle, speed, sprint, jump, and aim offset compatibility", requires=("crawl state", "transition predicates"), produces=("transition rule graphs"), verification=("anim_graph.add_transition_rule readback confirms predicates", "sprint/jump/aim offset gates remain reachable")),
            _node("crawl_output_pose_wiring", "Wire updated state machine path to output pose without breaking existing locomotion/aim offset graph", requires=("crawl state", "transition rule graphs"), produces=("connected output pose"), verification=("anim_graph.wire_state_machine_to_output_pose confirms pins")),
            _node("abp_compile_save_validation", "Compile, save, reload, and run disposable ABP transition validation", requires=("connected output pose",), produces=("validation report"), verification=("blueprint.compile_and_save succeeds", "readback confirms state/transition/output pose", "sprint/jump/aim offset regression checks pass")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="native_anim_graph_mutation",
                label="Use native AnimGraph mutation wrappers with readback validation",
                confidence=0.9,
                steps=("blueprint.scan targets", "add/reuse variables", "anim_graph.add_state", "anim_graph.add_transition_rule", "anim_graph.wire_state_machine_to_output_pose", "blueprint.compile_and_save", "run disposable transition proof"),
                pros=("directly maps to available Unreal bridge/plugin operations", "gives readback proof for each graph mutation"),
                cons=("requires live Unreal editor/plugin connection for mutation validation",),
            ),
            GapResolutionOption(
                key="plan_only_with_wrapper_generation",
                label="Generate wrapper/plugin updates first, then restart Unreal and validate",
                confidence=0.68,
                steps=("emit missing wrapper plan", "build plugin", "restart/reload Unreal if required", "run the same disposable validation fixture"),
                pros=("handles missing bridge bodies explicitly",),
                cons=("slower and cannot claim execution confidence until editor validation passes",),
                requires_approval=True,
            ),
        ),
        learning_recommendations=(
            "Persist the validated ABP crawl insertion recipe as an AnimBlueprint playbook.",
            "Register state/transition/output-pose readback fixtures for future locomotion features.",
        ),
        questions=("Which target skeleton/AnimBP owns Manny locomotion if ABP_Locomotion and ABP_Combat are both candidates?",),
    ),
    CapabilityPattern(
        key="unreal.niagara_gameplay_fx",
        labels=("Unreal Niagara gameplay FX system",),
        triggers=("niagara", "muzzle flash", "bullet impact", "bp_rifle", "bp_enemy", "gameplay cue", "replication-safe"),
        required_chain=(
            _node("niagara_target_scan", "Scan BP_Rifle, BP_Enemy, sockets, existing FX assets, and replication/event patterns", requires=("target Blueprint paths",), produces=("fx insertion points", "socket list", "network policy"), verification=("blueprint.scan confirms target graphs/components", "socket names and authority path are known")),
            _node("niagara_emitter_authoring", "Create or reuse Niagara muzzle flash and bullet impact emitters", requires=("fx requirements", "content path"), produces=("Niagara emitter assets"), verification=("niagara.create_emitter readback confirms assets")),
            _node("fx_socket_attachment", "Attach muzzle flash/impact systems to weapon or hit sockets/components", requires=("Niagara emitter assets", "socket list"), produces=("socket attachment graph"), verification=("blueprint.attach_to_socket readback confirms attachment/spawn path")),
            _node("fx_blueprint_events", "Add Blueprint events/functions for fire, impact, gameplay cue, and replication-safe execution", requires=("fx insertion points", "network policy"), produces=("event graph wiring"), verification=("blueprint.add_event readback confirms nodes/pins", "server/client cosmetic boundary is explicit")),
            _node("fx_compile_save_validation", "Compile/save targets and run disposable map validation for muzzle and impact FX", requires=("socket attachment graph", "event graph wiring"), produces=("validation map proof"), verification=("blueprint.compile_and_save succeeds", "unreal.create_validation_map proof records spawned effects")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="python_native_niagara_plus_blueprint_bridge",
                label="Use Python-native Niagara creation plus Blueprint bridge graph mutation",
                confidence=0.84,
                steps=("blueprint.scan BP_Rifle/BP_Enemy", "niagara.create_emitter for muzzle/impact", "blueprint.attach_to_socket", "blueprint.add_event replication-safe cue path", "blueprint.compile_and_save", "unreal.create_validation_map"),
                pros=("uses the Python Niagara path that already works for emitter creation", "keeps graph mutation readback visible"),
                cons=("socket names and replication policy must be verified before mutation",),
            ),
        ),
        learning_recommendations=(
            "Register reusable weapon FX socket/event patterns after validation.",
            "Persist disposable Niagara validation map fixture expectations.",
        ),
        questions=("Which muzzle socket and impact surface/material policy should be used if the Blueprints expose multiple options?",),
    ),
    CapabilityPattern(
        key="cross_app.blender_to_unreal_animation",
        labels=("Blender to Unreal animation pipeline",),
        triggers=("blender", "clean up", "mocap", "export it as fbx", "crawl blendspace", "retarget it to manny", "blender to unreal"),
        required_chain=(
            _node("blender_animation_source_scan", "Inspect Blender armature/action, frame range, root motion, scale, and cleanup requirements", requires=("active Blender scene or source file"), produces=("source animation profile"), verification=("Blender action/armature readback succeeds")),
            _node("blender_animation_cleanup", "Clean mocap curves, normalize root motion/scale, and preserve source action provenance", requires=("source animation profile"), produces=("cleaned animation action"), verification=("blender.clean_animation readback confirms curves/frame range")),
            _node("blender_fbx_export", "Export cleaned animation as Unreal-compatible FBX", requires=("cleaned animation action"), produces=("FBX animation file"), verification=("blender.export_fbx writes file", "export settings include axes/scale/skeleton")),
            _node("unreal_animation_import", "Import FBX animation into Unreal", requires=("FBX animation file", "target skeleton/project"), produces=("imported Unreal animation asset"), verification=("import_unreal_asset confirms Content Browser asset")),
            _node("unreal_retarget_to_manny", "Retarget imported animation to Manny skeleton", requires=("imported Unreal animation asset", "Manny skeleton/IK rig"), produces=("Manny-compatible animation"), verification=("unreal.retarget_animation readback confirms target skeleton")),
            _node("crawl_blendspace_update", "Create or update crawl BlendSpace and add samples", requires=("Manny-compatible animation", "ABP_Locomotion target"), produces=("crawl BlendSpace asset"), verification=("unreal.create_blendspace confirms samples/settings")),
            _node("abp_crawl_integration", "Add crawl BlendSpace to ABP_Locomotion with enter/exit gameplay validation", requires=("crawl BlendSpace asset", "gameplay input contract"), produces=("playable crawl locomotion"), verification=("anim_graph.add_state/transition and blueprint.compile_and_save succeed", "gameplay enter/exit proof is recorded")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="blender_export_then_unreal_retarget",
                label="Preserve Blender cleanup/export as a separate stage before Unreal import/retarget/ABP mutation",
                confidence=0.88,
                steps=("blender.clean_animation", "blender.export_fbx", "import_unreal_asset", "unreal.retarget_animation", "unreal.create_blendspace", "anim_graph.add_state/transition", "blueprint.compile_and_save", "gameplay validation"),
                pros=("keeps each host boundary explicit", "validates files before Unreal mutation"),
                cons=("requires both Blender source context and Unreal target skeleton/AnimBP",),
            ),
        ),
        learning_recommendations=(
            "Save validated Blender export settings for Manny-compatible animation.",
            "Register crawl BlendSpace integration as a reusable cross-DCC pipeline.",
        ),
        questions=("Which target Unreal skeleton/AnimBP should receive the imported animation if more than one exists?",),
    ),
    CapabilityPattern(
        key="cross_app.blender_to_unreal_prop",
        labels=("Blender to Unreal prop/mesh pipeline",),
        triggers=("blender to unreal prop", "prop pipeline", "lod0", "lod1", "collision", "material slots", "static mesh", "selected mesh", "apply transforms"),
        required_chain=(
            _node("blender_mesh_source_scan", "Inspect selected Blender meshes, object names, transforms, materials, and LOD requirements", requires=("active Blender scene or source file",), produces=("mesh source profile",), verification=("Blender selected mesh readback succeeds", "object/material/transform facts are captured")),
            _node("blender_mesh_cleanup", "Apply transforms, enforce naming convention, normalize origins/scale, and prepare LOD meshes", requires=("mesh source profile",), produces=("cleaned Blender mesh set",), verification=("readback confirms transforms, names, and LOD objects")),
            _node("blender_prop_fbx_export", "Export validated prop mesh FBX for Unreal static-mesh import", requires=("cleaned Blender mesh set",), produces=("FBX prop file",), verification=("FBX file exists", "export settings and selected objects are recorded")),
            _node("unreal_static_mesh_import", "Import FBX as Unreal static mesh assets in the requested content path", requires=("FBX prop file", "destination content path"), produces=("Unreal static mesh assets",), verification=("imported assets exist and load from Content Browser")),
            _node("unreal_material_collision_setup", "Assign/create material slots, configure collision, LOD settings, and save assets", requires=("Unreal static mesh assets", "material/collision policy"), produces=("validated prop asset package"), verification=("static mesh readback confirms LODs/material slots/collision", "save result is captured")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="blender_mesh_export_then_unreal_static_mesh_import",
                label="Preserve Blender mesh cleanup/export before Unreal static-mesh import and validation",
                confidence=0.88,
                steps=("blender.scan_scene_selection", "blender.clean_meshes", "blender.export_fbx", "unreal.import_static_mesh_fbx", "unreal.configure_static_mesh", "blueprint.compile_and_save or asset save", "readback validation"),
                pros=("keeps Blender and Unreal stages distinct", "validates the FBX handoff before Unreal asset mutation"),
                cons=("requires selected mesh/LOD policy and target content path"),
            ),
        ),
        learning_recommendations=(
            "Persist validated Blender static-mesh FBX export settings for Unreal.",
            "Register prop import/material/collision readback as a reusable pipeline fixture.",
        ),
        questions=("Which collision policy and material-slot policy should be used if the prompt does not specify them?",),
    ),
    CapabilityPattern(
        key="blender.scene_cleanup_tool",
        labels=("Blender scene cleanup operator/UI tool",),
        triggers=("scene cleanup operator", "cleanup operator", "ui panel", "dry-run preview", "duplicate material slots", "pack external textures", "rename selected objects"),
        required_chain=(
            _node("discover_blender_tool_patterns", "Find existing Blender bridge/tool UI patterns and operation registry entries", produces=("tool patterns", "callable candidates"), verification=("project search returns concrete files/symbols")),
            _node("design_blender_cleanup_operator", "Design operator/backend split for dry-run preview, rename/apply transform/material-slot/texture-pack operations", requires=("tool patterns",), produces=("operator contract", "UI contract"), verification=("inputs, side effects, and rollback behavior are explicit")),
            _node("generate_blender_cleanup_tool_code", "Generate complete Blender operator/UI code with backend function calls and validation messages", requires=("operator contract", "UI contract"), produces=("generated code patch"), verification=("generated code imports and compiles")),
            _node("validate_blender_cleanup_tool", "Validate generated code in a disposable workspace and fake Blender API harness before any host execution", requires=("generated code patch",), produces=("validation report"), verification=("temp workspace validation passes", "dry-run behavior is test-covered")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="project_code_tool_with_disposable_validation",
                label="Generate a real Blender UI/operator tool through code-quality and temp-workspace gates",
                confidence=0.86,
                steps=("code.search_project", "code.plan_expected_code", "code.validate_expected_code", "code.validate_patch_in_temp_workspace", "focused tests", "optional live Blender smoke"),
                pros=("matches first-try code quality path", "does not require Blender to be open until live smoke"),
                cons=("real Blender UI rendering still needs a connected host validation pass"),
            ),
        ),
        learning_recommendations=(
            "Promote validated Blender operator/UI skeletons into reusable code-generation examples.",
            "Store fake-bpy validation fixtures for dry-run scene cleanup tools.",
        ),
    ),
    CapabilityPattern(
        key="cross_app.maya_metahuman_facial",
        labels=("Maya to Unreal MetaHuman facial animation pipeline",),
        triggers=("metahuman", "metahumandna", "facial control rig", "facial animbp", "sequencer", "maya"),
        required_chain=(
            _node("maya_facial_rig_scan", "Inspect Maya facial controls, target expression, animation range, and export requirements", requires=("active Maya scene or facial rig file"), produces=("facial rig profile"), verification=("Maya controls and keyed channels read back")),
            _node("maya_facial_adjustment", "Apply facial control rig adjustment and key/export updated animation", requires=("facial rig profile", "expression spec"), produces=("facial animation file"), verification=("maya.adjust_facial_control_rig confirms keyed values", "exported animation file exists")),
            _node("metahuman_dna_propagation", "Propagate DNA changes with MetaHumanDNA if available and compatible", requires=("facial animation file", "MetaHuman DNA source"), produces=("DNA/provenance output or explicit skip reason"), verification=("metahuman.propagate_dna reports tool availability and output/provenance")),
            _node("unreal_facial_animation_import", "Import facial animation/DNA output into Unreal", requires=("facial animation file", "target MetaHuman asset"), produces=("Unreal facial animation asset"), verification=("import_unreal_asset confirms asset path")),
            _node("facial_animbp_slot_wiring", "Hook imported facial animation into the facial AnimBP slot", requires=("Unreal facial animation asset", "facial AnimBP slot"), produces=("AnimBP slot wiring"), verification=("unreal.hook_facial_animbp_slot readback confirms slot assignment")),
            _node("sequencer_playback_validation", "Validate facial animation playback in Sequencer", requires=("AnimBP slot wiring", "validation sequence"), produces=("Sequencer playback proof"), verification=("sequencer.validate_playback records playback result")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="maya_metahuman_dna_to_unreal_sequence",
                label="Keep Maya facial adjustment, MetaHumanDNA propagation, Unreal slot wiring, and Sequencer validation as distinct stages",
                confidence=0.86,
                steps=("maya.adjust_facial_control_rig", "export facial animation", "metahuman.propagate_dna if available", "import_unreal_asset", "unreal.hook_facial_animbp_slot", "sequencer.validate_playback"),
                pros=("does not confuse Maya/MetaHuman work with Blender animation transfer", "makes optional DNA tooling explicit"),
                cons=("requires target MetaHuman asset, DNA source, and facial AnimBP slot discovery",),
            ),
        ),
        learning_recommendations=(
            "Persist MetaHumanDNA tool availability and validated call shape.",
            "Register facial AnimBP slot wiring and Sequencer validation as reusable MetaHuman pipeline steps.",
        ),
        questions=("Which MetaHuman asset, DNA file, and facial AnimBP slot should be used if more than one candidate exists?",),
    ),
    CapabilityPattern(
        key="cross_app.animation_transfer",
        labels=("Cross-application animation acquisition and transfer",),
        triggers=("blender", "animation online", "online animation", "import animation", "import into unreal", "fbx", "retarget"),
        required_chain=(
            _node("blender_context_operation", "Blender context/internal operation", produces=("prepared source scene or rig data",), verification=("query Blender scene/object/rig state",)),
            _node("python_transform_helper", "Basic Python transform/helper step", requires=("source data",), produces=("normalized file or metadata",), verification=("helper return value and file existence",)),
            _node("online_animation_source", "Online animation source candidate", requires=("search terms", "license constraints"), produces=("downloadable animation asset",), verification=("source link, relevance, and license recorded",)),
            _node("asset_ingest", "Animation asset download/ingest", requires=("approved source",), produces=("local animation file",), verification=("file exists and format is supported",)),
            _node("unreal_animation_import", "Unreal animation import", requires=("local animation file", "target skeleton/project"), produces=("imported Unreal animation asset",), verification=("asset exists in Content Browser and loads",)),
            _node("post_import_tool", "Post-import internal tool operation", requires=("imported asset",), produces=("final connected/processed result",), verification=("tool result and affected asset state",)),
        ),
        resolution_options=(
            GapResolutionOption(
                key="internal_then_acquire_then_unreal",
                label="Run internal prep, acquire animation with approval, import into Unreal, then continue tools",
                confidence=0.76,
                steps=("run Blender/internal prep", "run Python normalization", "find animation source and report links/relevance", "pause for ingest approval/license", "import into Unreal", "run post-import tool and validate"),
                pros=("handles mixed app workflow explicitly", "keeps external asset approval visible"),
                cons=("depends on source availability and target skeleton compatibility",),
                requires_approval=True,
            ),
        ),
        learning_recommendations=(
            "Save validated animation source/import mappings as reusable cross-app capability knowledge.",
            "Register successful Blender-to-Unreal animation import steps as a reusable mixed operation sequence.",
        ),
        questions=("Which target Unreal skeleton/AnimBP should receive the imported animation if more than one exists?",),
    ),
)


def _matched_patterns(prompt: str, decision: dict[str, Any]) -> list[CapabilityPattern]:
    lower = (prompt or "").lower()
    route_blob = " ".join(str(decision.get(key) or "") for key in ("route", "host", "intent_category", "provider")).lower()
    scored: list[tuple[int, CapabilityPattern]] = []
    for pattern in PATTERNS:
        score = 0
        for trigger in pattern.triggers:
            if trigger in lower or trigger in route_blob:
                score += 1
        if score:
            scored.append((score, pattern))
    scored.sort(key=lambda item: (-item[0], item[1].key.count(".")))
    matches = [pattern for _score, pattern in scored]
    operation_runner_request = bool(
        re.search(
            r"\b(operation\s+(?:runner|catalog)|registered\s+(?:unreal|dcc|host)?\s*operations?|"
            r"edit\s+(?:its|operation)\s+arguments?\s+as\s+json)\b",
            lower,
        )
    )
    if not operation_runner_request:
        matches = [
            pattern
            for pattern in matches
            if pattern.key != "code.qt_operation_runner_ui"
        ]
    wants_general_code_implementation = bool(
        str(decision.get("route") or "") in {"target_discovery", "code_agent"}
        and re.search(
            r"\b(build|create|implement|refactor|add|write|develop)\b",
            lower,
        )
        and re.search(
            r"\b(code|python|service|registry|cache|scheduler|parser|decoder|"
            r"console|widget|ui|plugin|class|module|tests?|multi-file)\b",
            lower,
        )
    )
    if (
        wants_general_code_implementation
        and not operation_runner_request
        and not any(pattern.key == "code.multi_file_implementation" for pattern in matches)
    ):
        matches.insert(
            0,
            next(
                pattern
                for pattern in PATTERNS
                if pattern.key == "code.multi_file_implementation"
            ),
        )
    specific_keys = {pattern.key for pattern in matches}
    wants_blender_prop_pipeline = bool(
        "blender" in lower
        and "unreal" in lower
        and re.search(r"\b(prop|mesh|static mesh|lod0|lod1|collision|material slots?|apply transforms?)\b", lower)
    )
    wants_blender_scene_tool = bool(
        "blender" in lower
        and (
            re.search(
                r"\b(operator|ui panel|dry-run|dry run|duplicate material slots?|"
                r"pack external textures|rename selected objects)\b",
                lower,
            )
            or (
                re.search(r"\b(scene cleanup|cleanup)\b", lower)
                and re.search(r"\b(tool|operator|panel)\b", lower)
            )
        )
    )
    wants_blender_animation_pipeline = bool(
        "blender" in lower
        and "unreal" in lower
        and re.search(r"\b(animation|anim|mocap|armature|action|retarget|skeleton|blendspace|root motion|crawl)\b", lower)
    )
    if wants_blender_prop_pipeline:
        matches = [
            pattern for pattern in matches
            if pattern.key not in {"cross_app.blender_to_unreal_animation", "cross_app.animation_transfer", "external.asset_acquisition"}
        ]
        if not any(pattern.key == "cross_app.blender_to_unreal_prop" for pattern in matches):
            matches.insert(0, next(pattern for pattern in PATTERNS if pattern.key == "cross_app.blender_to_unreal_prop"))
    if wants_blender_scene_tool:
        matches = [
            pattern for pattern in matches
            if pattern.key not in {"cross_app.blender_to_unreal_animation", "cross_app.animation_transfer", "cross_app.blender_to_unreal_prop", "external.asset_acquisition"}
        ]
        if not any(pattern.key == "blender.scene_cleanup_tool" for pattern in matches):
            matches.insert(0, next(pattern for pattern in PATTERNS if pattern.key == "blender.scene_cleanup_tool"))
    if not wants_blender_animation_pipeline:
        matches = [pattern for pattern in matches if pattern.key != "cross_app.blender_to_unreal_animation"]
    specific_keys = {pattern.key for pattern in matches}
    wants_external_animation = any(term in lower for term in ("online animation", "find an animation", "download animation", "animation online"))
    if not wants_external_animation and any(key in specific_keys for key in ("cross_app.blender_to_unreal_animation", "cross_app.maya_metahuman_facial")):
        matches = [pattern for pattern in matches if pattern.key != "cross_app.animation_transfer"]
    if "cross_app.blender_to_unreal_animation" in specific_keys:
        matches = [pattern for pattern in matches if pattern.key != "unreal.anim_blueprint_locomotion_crawl"]
    if "unreal.anim_blueprint_locomotion_crawl" in specific_keys and not any(
        term in lower for term in ("stamina", "energy", "recovery rate", "drain rate")
    ):
        matches = [pattern for pattern in matches if pattern.key != "unreal.character_stamina"]
    if any(key in specific_keys for key in ("unreal.anim_blueprint_locomotion_crawl", "unreal.niagara_gameplay_fx")):
        matches = [pattern for pattern in matches if pattern.key != "generic.unreal"]
    return matches


def _generic_pattern(prompt: str, decision: dict[str, Any]) -> CapabilityPattern:
    host = str(decision.get("host") or "").strip()
    route = str(decision.get("route") or "general").strip()
    label = f"{host or route or 'general'} objective gap plan"
    return CapabilityPattern(
        key=f"generic.{_slug(host or route)}",
        labels=(label,),
        triggers=(),
        required_chain=(
            _node("goal_normalization", "Normalize user goal from prompt plus thread context", produces=("success criteria",), verification=("goal and constraints are explicit",)),
            _node("current_capability_check", "Check current capability graph and local project facts", requires=("project/tool context",), produces=("known capabilities", "missing links"), verification=("evidence has source paths or provider metadata",)),
            _node("gap_discovery", "Discover intermediate capabilities needed to connect known A to requested Z", requires=("known capabilities", "goal"), produces=("resolution candidates",), verification=("each missing link has prerequisites and validation",)),
            _node("option_ranking", "Rank resolution options by fit, safety, confidence, and validation path", requires=("resolution candidates",), produces=("recommended path",), verification=("tradeoffs and fallback are visible",)),
            _node("learning_capture", "Capture reusable technique and future capability recommendation", requires=("completed or blocked plan",), produces=("knowledge update recommendation",), verification=("recommendation has source/evidence and is user-approvable",)),
        ),
        resolution_options=(
            GapResolutionOption(
                key="compose_existing_capabilities",
                label="Compose existing local capabilities before creating new ones",
                confidence=0.78,
                steps=("inspect project/tool context", "find reusable operations", "insert missing prerequisite steps", "validate result"),
                pros=("avoids unnecessary new systems", "works with project conventions"),
                cons=("depends on index/host context quality",),
            ),
            GapResolutionOption(
                key="research_then_persist",
                label="Research missing techniques, then persist structured local knowledge",
                confidence=0.66,
                steps=("identify missing capability", "request/perform authoritative research if allowed", "convert result to local playbook/capability", "use it in the plan"),
                pros=("improves future attempts",),
                cons=("requires source permission and validation",),
                requires_approval=True,
                research_hint="Use official/provider docs first, then verified internal examples.",
            ),
        ),
        learning_recommendations=(
            "If a missing link was discovered, suggest saving it as a reusable capability relationship.",
            "If planning required repeated manual context gathering, suggest adding a resolver or index field.",
            "If validation was weak, suggest adding a focused validation operation.",
        ),
    )


def _is_quick_direct_action(decision: dict[str, Any]) -> bool:
    prompt = str(decision.get("prompt") or decision.get("original_prompt") or "").lower()
    if re.search(r"\b(pipeline|workflow|ui|user interface|panel|window|widget|tool|operator|test harness|generate|scaffold|build)\b", prompt):
        return False
    if decision.get("requires_plan") or decision.get("requires_confirmation"):
        return False
    if str(decision.get("risk_level") or "").lower() in {"medium", "high"}:
        return False
    if str(decision.get("compound_kind") or "atomic") != "atomic":
        return False
    mutation = str(decision.get("mutation_scope") or "")
    if mutation and mutation != "read_only":
        return False
    route = str(decision.get("route") or "")
    return route in {"dcc_execute", "function_execution", "project_search", "chat", "open_file"}


def _quick_direct_pattern(prompt: str, decision: dict[str, Any]) -> CapabilityPattern:
    host = str(decision.get("host") or "").strip()
    route = str(decision.get("route") or "direct").strip()
    return CapabilityPattern(
        key=f"quick.{_slug(host or route)}",
        labels=(f"{host or route} quick action",),
        triggers=(),
        required_chain=(
            _node(
                "target_resolution",
                "Resolve the requested target from current context",
                produces=("target",),
                verification=("target exists or the action reports that it could not be found",),
            ),
            _node(
                "direct_action",
                "Run the direct low-risk action",
                requires=("target",),
                produces=("completed action",),
                verification=("operation reports success or a clear failure",),
            ),
        ),
        resolution_options=(),
        learning_recommendations=(),
    )


def _contextual_knowledge_evidence(prompt: str, decision: dict[str, Any]) -> tuple[str, ...]:
    try:
        from tech_connector.services.ai_work_memory_service import relevant_ai_work_entries, relevant_contextual_knowledge

        rows = relevant_contextual_knowledge(decision.get("settings") or {}, prompt, limit=8)
        work_rows = relevant_ai_work_entries(decision.get("settings") or {}, prompt, host=str(decision.get("host") or ""), limit=8)
    except Exception:
        return ()
    evidence: list[str] = []
    for row in rows:
        subject = str(row.get("subject") or "").strip()
        relation = str(row.get("relation") or "").strip()
        value = str(row.get("value") or row.get("fact") or "").strip()
        if subject or value:
            evidence.append(f"validated contextual knowledge: {subject} {relation} {value}".strip())
    for bucket, prefix in (("recent", "validated work memory"), ("locked", "locked work memory")):
        for row in list(work_rows.get(bucket) or [])[:4]:
            parts = [
                row.get("label") or "",
                row.get("goal") or "",
                row.get("summary") or "",
                row.get("local_path") or "",
                row.get("workflow_path") or "",
                row.get("knowledge_path") or "",
            ]
            text = " ".join(str(part) for part in parts if part).strip()
            if text:
                evidence.append(f"{prefix}: {text}")
    return tuple(evidence)


def _capability_registry_evidence(prompt: str, decision: dict[str, Any]) -> tuple[str, ...]:
    registry = decision.get("capability_registry")
    if registry is None:
        registry_path = decision.get("capability_registry_path")
        if registry_path:
            try:
                from tech_connector.services.capability_registry import CapabilityRegistry

                registry = CapabilityRegistry(Path(str(registry_path)))
            except Exception:
                registry = None
    if registry is None or not hasattr(registry, "lookup"):
        return ()
    try:
        entries = registry.lookup(prompt, limit=8)
    except Exception:
        return ()
    evidence: list[str] = []
    for entry in entries:
        try:
            data = entry.to_dict()
        except Exception:
            data = dict(entry or {})
        if not data:
            continue
        parts = [
            data.get("name") or "",
            data.get("category") or "",
            data.get("source") or "",
            " ".join(data.get("keywords") or []),
            data.get("notes") or "",
            data.get("file_path") or "",
        ]
        text = " ".join(str(part) for part in parts if part).strip()
        if text:
            evidence.append(f"registered capability: {text}")
    return tuple(evidence)


def _known_capability_evidence(decision: dict[str, Any], prompt: str = "") -> tuple[str, ...]:
    evidence: list[str] = []
    for item in list(decision.get("context_resolvers") or [])[:6]:
        evidence.append(f"context resolver: {item}")
    for item in list(decision.get("deterministic_steps") or [])[:6]:
        evidence.append(f"deterministic step: {item}")
    for item in list(decision.get("capability_gaps") or [])[:6]:
        evidence.append(f"known gap: {item}")
    evidence.extend(_contextual_knowledge_evidence(prompt, decision))
    evidence.extend(_capability_registry_evidence(prompt, decision))
    return _uniq(evidence)


def _strategy_by_key(key: str) -> CapabilityResolutionStrategy:
    for strategy in RESOLUTION_STRATEGIES:
        if strategy.key == key:
            return strategy
    return RESOLUTION_STRATEGIES[0]


def _strategy_keys_for_node(node: CapabilityNode, decision: dict[str, Any]) -> list[str]:
    status = str(node.status or "")
    label = node.label.lower()
    allow_research = bool(decision.get("allow_external_research"))
    allow_ingestion = bool(decision.get("allow_ingestion"))
    if node.key == "user_goal":
        return ["project_index_search"]
    if status == "known":
        return ["internal_function", "internal_workflow", "compose_internal_functions"]
    keys = ["project_index_search", "local_documentation", "compose_internal_functions"]
    if _is_external_asset_source_node(node) and allow_ingestion:
        keys.extend(["asset_source_search", "plugin_marketplace"])
        if _prompt_wants_generated_asset(decision):
            keys.append("ai_animation_service")
    if any(term in label for term in ("plugin", "pose search", "motion matching", "api", "unreal", "maya", "documentation")):
        keys.append("official_documentation")
    if allow_research and not any(term in label for term in ("plugin", "repository", "marketplace")):
        keys.append("official_documentation")
    if allow_ingestion:
        keys.extend(["github_ingest", "plugin_marketplace"])
    keys.append("generate_new_code")
    if node.requires:
        keys.append("ask_user")
    return list(_uniq(keys))


def _is_animation_source_node(node: CapabilityNode) -> bool:
    text = f"{node.key} {node.label}".lower()
    return any(term in text for term in ("online_animation_source", "animation source", "motion library", "mocap", "animation asset"))


def _is_external_asset_source_node(node: CapabilityNode) -> bool:
    text = f"{node.key} {node.label}".lower()
    return _is_animation_source_node(node) or any(
        term in text
        for term in ("external_asset_source", "asset source", "marketplace/source", "3d asset", "mesh", "model", "texture", "material")
    )


def _prompt_wants_generated_asset(decision: dict[str, Any]) -> bool:
    text = " ".join(
        str(decision.get(key) or "")
        for key in ("prompt", "original_prompt", "request", "goal", "literal_request")
    ).lower()
    return any(
        term in text
        for term in (
            "text to animation", "text-to-animation", "video to animation", "video-to-animation",
            "text to mesh", "text-to-mesh", "image to mesh", "image-to-mesh", "generate mesh",
            "from video", "from text", "from image", "ai animation", "ai asset", "ai mesh",
        )
    )


def _provider_candidates_for_node(node: CapabilityNode, decision: dict[str, Any]) -> list[dict[str, Any]]:
    if not _is_external_asset_source_node(node):
        return []
    prompt_text = " ".join(str(decision.get(key) or "") for key in ("prompt", "original_prompt", "request", "goal", "literal_request")).lower()
    candidates: list[dict[str, Any]] = []
    try:
        from tech_connector.services.capability_acquisition_service import KNOWN_CAPABILITY_SOURCES
    except Exception:
        KNOWN_CAPABILITY_SOURCES = {}
    animation_node = _is_animation_source_node(node)
    if animation_node:
        wanted_keys = ("mixamo", "actorcore", "rokoko", "fab_marketplace")
        preview_plan = "Open the provider link, preview candidate animation clips, inspect motion style, skeleton/FBX options, and license terms."
        use_plan = "After approval, download/export a compatible animation file, record provenance/license, import into Unreal, retarget if needed, and validate playback."
    elif any(term in prompt_text for term in ("texture", "material", "hdri")):
        wanted_keys = ("poly_haven", "quixel", "fab_marketplace")
        preview_plan = "Open the provider link, preview candidate assets, inspect texture/material quality, resolution, formats, and license terms."
        use_plan = "After approval, download/export compatible texture/material files, record provenance/license, import into the target host, and validate material assignments."
    else:
        wanted_keys = ("poly_haven", "quixel", "fab_marketplace")
        preview_plan = "Open the provider link, preview candidate assets, inspect mesh/material/texture quality, formats, scale, and license terms."
        use_plan = "After approval, download/export compatible asset files, record provenance/license, import into the target host, and validate scale/materials."
    for key in wanted_keys:
        source = dict(KNOWN_CAPABILITY_SOURCES.get(key) or {})
        if not source:
            continue
        candidates.append(
            {
                "provider_key": key,
                "name": source.get("name") or key,
                "source_type": source.get("source_type") or "asset_source",
                "url": source.get("url") or "",
                "cost": source.get("cost") or "",
                "license": source.get("license") or "",
                "automation": source.get("automation") or "",
                "success_probability": source.get("success_probability") or 0.0,
                "compatibility": source.get("compatibility") or {},
                "description": source.get("description") or "",
                "requires_user_selection": True,
                "preview_plan": preview_plan,
                "use_plan": use_plan,
            }
        )
    if _prompt_wants_generated_asset(decision):
        candidates.extend(
            [
                {
                    "provider_key": "video_to_animation_service",
                    "name": "Video-to-animation service",
                    "source_type": "ai_service",
                    "url": "",
                    "cost": "Varies",
                    "license": "Provider terms required",
                    "automation": "Semi",
                    "success_probability": 0.68,
                    "compatibility": {"fbx": "preferred", "unreal": "requires retarget/import validation"},
                    "description": "Candidate service/tool that extracts motion from uploaded video and exports animation data.",
                    "requires_user_selection": True,
                    "privacy_review_required": True,
                    "preview_plan": "Show service/provider link, required upload inputs, privacy terms, sample output format, and expected skeleton/FBX compatibility.",
                    "use_plan": "After approval, submit source video or selected local media, export animation data, record provenance/terms, import into Unreal, and validate retargeted motion.",
                },
                {
                    "provider_key": "text_to_animation_service",
                    "name": "Text-to-animation service",
                    "source_type": "ai_service",
                    "url": "",
                    "cost": "Varies",
                    "license": "Provider terms required",
                    "automation": "Semi",
                    "success_probability": 0.58,
                    "compatibility": {"fbx": "preferred", "unreal": "requires import validation"},
                    "description": "Candidate service/tool that generates motion from a text prompt and exports animation data.",
                    "requires_user_selection": True,
                    "privacy_review_required": True,
                    "preview_plan": "Show service/provider link, prompt controls, generated preview options, terms, and available export formats.",
                    "use_plan": "After approval, generate or select a previewed clip, export animation data, record provenance/terms, import into Unreal, and validate motion quality.",
                },
            ]
        )
        if not _is_animation_source_node(node):
            candidates.append(
                {
                    "provider_key": "text_or_image_to_mesh_service",
                    "name": "Text/image-to-mesh service",
                    "source_type": "ai_service",
                    "url": "",
                    "cost": "Varies",
                    "license": "Provider terms required",
                    "automation": "Semi",
                    "success_probability": 0.55,
                    "compatibility": {"obj": "common", "fbx": "preferred", "unreal": "requires import/material validation"},
                    "description": "Candidate service/tool that generates a mesh from text or image input.",
                    "requires_user_selection": True,
                    "privacy_review_required": True,
                    "preview_plan": "Show service/provider link, input requirements, generated mesh preview options, texture/material export support, and terms.",
                    "use_plan": "After approval, generate or select a previewed mesh, export asset files, record provenance/terms, import into the target host, and validate scale/materials.",
                }
            )
    candidates.append(
        {
            "provider_key": "github_tool_search",
            "name": "GitHub tool search",
            "source_type": "github",
            "url": "https://github.com/search",
            "cost": "Free",
            "license": "Repository-specific",
            "automation": "Semi",
            "success_probability": 0.64,
            "compatibility": {"python": "requires wrapper/indexing"},
            "description": "Search for a public repository that provides an importer, downloader, retargeter, or animation utility.",
            "requires_user_selection": True,
            "preview_plan": "Show the top repository links, README/license summary, maintainer/activity signals, and expected tool entry points before ingesting.",
            "use_plan": "After approval, ingest the selected repository into external_tools, index callable symbols, register capabilities, and run through a wrapper/validation step.",
        }
    )
    if "mixamo" in prompt_text:
        candidates.sort(key=lambda item: 0 if item["provider_key"] == "mixamo" else 1)
    elif "poly haven" in prompt_text or "polyhaven" in prompt_text:
        candidates.sort(key=lambda item: 0 if item["provider_key"] == "poly_haven" else 1)
    elif "quixel" in prompt_text or "megascans" in prompt_text:
        candidates.sort(key=lambda item: 0 if item["provider_key"] == "quixel" else 1)
    elif _prompt_wants_generated_asset(decision):
        candidates.sort(key=lambda item: 0 if item["provider_key"] == "github_tool_search" else 1)
    else:
        candidates.sort(key=lambda item: (-float(item.get("success_probability") or 0.0), item.get("name", "")))
    return candidates


def _resolution_strategy_plan(
    nodes: list[CapabilityNode],
    decision: dict[str, Any],
    *,
    max_strategies_per_node: int = 8,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for node in nodes:
        strategies = [_strategy_by_key(key) for key in _strategy_keys_for_node(node, decision)]
        strategies = sorted(
            strategies,
            key=lambda item: (
                item.requires_approval,
                item.requires_internet and not bool(decision.get("allow_external_research")),
                -item.confidence,
                -item.reliability,
            ),
        )
        chosen = _choose_strategy_for_node(node, strategies, decision)
        provider_candidates = _provider_candidates_for_node(node, decision)
        plan.append(
            {
                "capability": node.key,
                "label": node.label,
                "status": node.status,
                "chosen_strategy": chosen,
                "strategies": [strategy.to_dict() for strategy in strategies[:max_strategies_per_node]],
                "provider_candidates": provider_candidates,
                "review_required": bool(provider_candidates),
            }
        )
    return plan


def _choose_strategy_for_node(
    node: CapabilityNode,
    strategies: list[CapabilityResolutionStrategy],
    decision: dict[str, Any],
) -> str:
    if not strategies:
        return ""
    status = str(node.status or "")
    label = node.label.lower()
    keys = {strategy.key for strategy in strategies}
    allow_research = bool(decision.get("allow_external_research"))
    allow_ingestion = bool(decision.get("allow_ingestion"))
    if status == "known":
        for key in ("internal_function", "internal_workflow", "compose_internal_functions"):
            if key in keys:
                return key
    if _is_external_asset_source_node(node):
        if _prompt_wants_generated_asset(decision) and allow_ingestion and "github_ingest" in keys:
            return "github_ingest"
        if _prompt_wants_generated_asset(decision) and "ai_animation_service" in keys:
            return "ai_animation_service"
        if allow_ingestion and "asset_source_search" in keys:
            return "asset_source_search"
    if allow_ingestion and any(term in label for term in ("online", "source", "download", "ingest", "asset")):
        if "github_ingest" in keys:
            return "github_ingest"
    if allow_research and any(term in label for term in ("plugin", "pose search", "motion matching", "api", "documentation", "unreal", "maya", "research")):
        if "official_documentation" in keys:
            return "official_documentation"
    if "project_index_search" in keys:
        return "project_index_search"
    return strategies[0].key


def _adaptive_sequence(strategy_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sequence: list[dict[str, Any]] = []
    for item in strategy_plan:
        chosen = str(item.get("chosen_strategy") or "")
        label = str(item.get("label") or item.get("capability") or "")
        if chosen in {"internal_function", "internal_workflow", "compose_internal_functions"}:
            action = "execute_internal"
        elif chosen in {"project_index_search", "local_documentation", "official_documentation"}:
            action = "discover_then_continue"
        elif chosen in {"github_ingest", "plugin_marketplace", "asset_source_search", "ai_animation_service"}:
            action = "request_approval_acquire_validate_register"
        elif chosen == "generate_new_code":
            action = "generate_validate_register"
        elif chosen == "ask_user":
            action = "ask_user_then_continue"
        else:
            action = "resolve_then_continue"
        sequence.append(
            {
                "capability": item.get("capability", ""),
                "label": label,
                "status": item.get("status", ""),
                "strategy": chosen,
                "action": action,
                "handoff": "registered_capability_or_verified_result",
            }
        )
    return sequence


def _action_type_by_key(key: str) -> OperationActionType:
    for action_type in ACTION_TYPES:
        if action_type.key == key:
            return action_type
    return ACTION_TYPES[0]


def _action_keys_for_sequence_item(item: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    strategy = str(item.get("strategy") or "")
    label = str(item.get("label") or "").lower()
    capability = str(item.get("capability") or "").lower()
    status = str(item.get("status") or "")
    allow_ingestion = bool(decision.get("allow_ingestion"))
    keys: list[str] = []
    if capability == "user_goal":
        return []
    if strategy in {"internal_function", "internal_workflow", "compose_internal_functions"}:
        keys.append("execute_internal_function")
    elif strategy in {"project_index_search", "local_documentation"}:
        keys.append("execute_internal_function")
    elif strategy == "official_documentation":
        keys.append("web_knowledge_search")
    elif strategy == "github_ingest":
        keys.extend(["github_candidate_review", "download_or_ingest_asset", "register_capability"])
    elif strategy == "plugin_marketplace":
        keys.extend(["plugin_candidate_review", "register_capability"])
    elif strategy == "asset_source_search":
        keys.extend(["plugin_candidate_review", "download_or_ingest_asset", "register_capability"])
    elif strategy == "ai_animation_service":
        keys.extend(["plugin_candidate_review", "generate_code_or_wrapper", "download_or_ingest_asset", "register_capability"])
    elif strategy == "generate_new_code":
        keys.extend(["generate_code_or_wrapper", "register_capability"])
    elif strategy == "ask_user":
        keys.append("validate_result")
    else:
        keys.append("execute_internal_function")

    domain_action_map = {
        "abp_target_scan": ["blueprint.scan"],
        "crawl_variable_contract": ["blueprint.add_event"],
        "crawl_state_creation": ["anim_graph.add_state"],
        "crawl_transition_rules": ["anim_graph.add_transition_rule"],
        "crawl_output_pose_wiring": ["anim_graph.wire_state_machine_to_output_pose"],
        "abp_compile_save_validation": ["blueprint.compile_and_save", "unreal.create_validation_map"],
        "niagara_target_scan": ["blueprint.scan"],
        "niagara_emitter_authoring": ["niagara.create_emitter"],
        "fx_socket_attachment": ["blueprint.attach_to_socket"],
        "fx_blueprint_events": ["blueprint.add_event"],
        "fx_compile_save_validation": ["blueprint.compile_and_save", "unreal.create_validation_map"],
        "blender_animation_source_scan": ["blender.scan_animation"],
        "blender_animation_cleanup": ["blender.clean_animation"],
        "blender_fbx_export": ["blender.export_fbx"],
        "blender_mesh_source_scan": ["blender.scan_scene_selection"],
        "blender_mesh_cleanup": ["blender.clean_meshes"],
        "blender_prop_fbx_export": ["blender.export_fbx"],
        "unreal_static_mesh_import": ["unreal.import_static_mesh_fbx"],
        "unreal_material_collision_setup": ["unreal.configure_static_mesh"],
        "unreal_animation_import": ["import_unreal_asset"],
        "unreal_retarget_to_manny": ["unreal.retarget_animation"],
        "crawl_blendspace_update": ["unreal.create_blendspace"],
        "abp_crawl_integration": ["blueprint.scan", "anim_graph.add_state", "anim_graph.add_transition_rule", "anim_graph.wire_state_machine_to_output_pose", "blueprint.compile_and_save", "unreal.create_validation_map"],
        "maya_facial_rig_scan": ["maya.scan_facial_rig"],
        "maya_facial_adjustment": ["maya.adjust_facial_control_rig"],
        "metahuman_dna_propagation": ["metahuman.propagate_dna"],
        "unreal_facial_animation_import": ["import_unreal_asset"],
        "facial_animbp_slot_wiring": ["blueprint.scan", "unreal.hook_facial_animbp_slot", "blueprint.compile_and_save"],
        "sequencer_playback_validation": ["sequencer.validate_playback"],
        "code_target_scan": ["code.search_project"],
        "code_symbol_inspection": ["code.inspect_symbols"],
        "code_change_design": ["code.plan_patch"],
        "code_expected_artifact": ["code.plan_expected_code"],
        "code_expected_artifact_validation": ["code.validate_expected_code"],
        "code_temp_workspace_validation": ["code.validate_patch_in_temp_workspace"],
        "qt_ui_pattern_scan": ["code.search_project"],
        "operation_catalog_scan": ["code.inspect_symbols"],
        "qt_operation_ui_design": ["code.plan_patch"],
        "qt_expected_code_artifact": ["code.plan_expected_code"],
        "qt_expected_code_validation": ["code.validate_expected_code"],
        "qt_temp_workspace_validation": ["code.validate_patch_in_temp_workspace"],
        "qt_operation_ui_patch": ["code.apply_patch"],
        "qt_operation_ui_tests": ["code.update_tests"],
        "qt_operation_ui_validation": ["code.run_tests"],
        "discover_blender_tool_patterns": ["code.search_project"],
        "design_blender_cleanup_operator": ["code.plan_patch"],
        "generate_blender_cleanup_tool_code": ["code.plan_expected_code"],
        "validate_blender_cleanup_tool": ["code.validate_expected_code", "code.validate_patch_in_temp_workspace", "code.update_tests", "code.run_tests"],
        "code_patch_application": ["code.apply_patch"],
        "code_test_update": ["code.update_tests"],
        "code_validation_report": ["code.run_tests"],
    }
    is_domain_mapped = capability in domain_action_map
    if is_domain_mapped:
        keys = list(domain_action_map[capability])

    host_text = f"{label} {capability} {decision.get('host') or ''}".lower()
    direct_dcc_route = str(decision.get("route") or "") in {
        "dcc_query",
        "dcc_execute",
        "unreal_capability",
    }
    if not is_domain_mapped and (direct_dcc_route or status != "known") and any(term in host_text for term in ("blender", "maya", "houdini", "motionbuilder", "substance", "unity", "unreal")):
        keys.insert(0, "run_dcc_operation")
    if not is_domain_mapped and ("python" in host_text or "wrapper" in host_text):
        keys.append("run_python_function")
    if not is_domain_mapped and allow_ingestion and strategy in {"github_ingest", "plugin_marketplace"} and any(term in label for term in ("animation", "fbx", "asset", "motion", "clip")):
        keys.append("download_or_ingest_asset")
    if not is_domain_mapped and capability != "user_goal" and (
        ("import" in host_text and "unreal" in host_text)
        or (
            strategy not in {"project_index_search", "local_documentation", "official_documentation"}
            and ("unreal" in label or "animgraph" in label or "content browser" in label)
        )
    ):
        keys.append("import_unreal_asset")
    keys.append("validate_result")
    return list(_uniq(keys))


def _operation_action_catalog() -> list[dict[str, Any]]:
    return [action_type.to_dict() for action_type in ACTION_TYPES]


def _planned_call_for_action(item: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    action_type = str(item.get("action_type") or "")
    capability = str(item.get("capability") or "")
    prompt = str(decision.get("prompt") or decision.get("original_prompt") or "")
    host = _execution_context_for_action(item).get("host", "")
    capability_text = f"{capability} {prompt}".lower()
    wants_qt_operation_runner = any(
        term in capability_text
        for term in (
            "operation runner",
            "operation catalog",
            "registered unreal/dcc operation",
            "edit its arguments as json",
        )
    )
    wants_rollback_journal = any(term in capability_text for term in ("rollback journal", "failed write", "recovery after a failed"))
    wants_prompt_router_evidence = any(term in capability_text for term in ("prompt router", "fuzz regression", "attribution paths", "route evidence"))
    if wants_qt_operation_runner:
        expected_code_dependencies = ["Qt pattern scan", "operation catalog scan", "existing execution-service dispatch path"]
        expected_code_payload = {
            "expected_files": [
                {
                    "path": "tech_connector/ui/operation_runner_panel.py",
                    "purpose": "Reusable PySide panel for browsing registered operations, editing JSON args, and non-blocking run/queue dispatch.",
                },
                {
                    "path": "tech_connector/app/main_window_ui.py or app tab composition module",
                    "purpose": "Add OperationRunnerPanel to the app/tab layout without duplicating existing workflow UI.",
                },
                {
                    "path": "examples/tech_connector/tests/test_operation_runner_panel.py",
                    "purpose": "Focused tests for catalog loading, JSON template generation, and worker payload creation.",
                },
            ],
            "expected_imports": [
                "PySide6.QtCore.QThread, Signal, Qt",
                "PySide6.QtWidgets.QWidget, QComboBox, QLineEdit, QPushButton, QPlainTextEdit, QTableWidget, QTableWidgetItem",
                "tech_connector.services.unreal.unreal_operation_service.operation_catalog",
                "tech_connector.services.unreal.unreal_operation_service.unreal_operation_payload",
                "tech_connector.services.dcc.dcc_operation_service.dcc_operation_registry",
                "tech_connector.router.command_router.CommandRouter",
            ],
            "expected_classes": [
                {"name": "OperationRow", "kind": "dataclass", "fields": ["host", "key", "label", "function", "required", "optional", "mutates_project"]},
                {"name": "OperationBackend", "kind": "service adapter", "methods": ["run_operation(host, operation_key, params)"]},
                {"name": "OperationRunWorker", "kind": "QThread", "signals": ["progress = Signal(str)", "finished = Signal(bool, object)"], "methods": ["__init__(host, operation_key, args_json)", "run()"]},
                {"name": "OperationRunnerPanel", "kind": "QWidget", "methods": ["__init__()", "refresh_catalog()", "populate_args_template()", "run_selected_operation()", "_on_finished()", "_set_rows()", "_selected_row()"]},
            ],
            "method_contracts": [
                {"method": "OperationRow.from_unreal", "inputs": ["operation catalog item"], "side_effects": [], "errors": ["missing key/function metadata"], "returns_or_emits": ["OperationRow"]},
                {"method": "OperationRow.from_dcc", "inputs": ["host", "DCC operation registry item"], "side_effects": [], "errors": ["missing function metadata"], "returns_or_emits": ["OperationRow"]},
                {"method": "OperationBackend.run_operation", "inputs": ["host", "operation_key", "params"], "side_effects": ["calls CommandRouter backend or injected fake"], "errors": ["unknown_host", "backend_exception"], "returns_or_emits": ["structured result with label/ok/result"]},
                {"method": "OperationRunnerPanel.refresh_catalog", "inputs": ["Unreal catalog", "DCC registries"], "side_effects": ["replaces operation table rows", "refreshes argument template for selection"], "errors": ["catalog import unavailable"], "returns_or_emits": ["row count", "error text"]},
                {"method": "OperationRunnerPanel.populate_args_template", "inputs": ["selected OperationRow"], "side_effects": ["writes formatted JSON to args editor"], "errors": ["operation_not_selected"], "returns_or_emits": ["JSON argument template"]},
                {"method": "OperationRunnerPanel.run_selected_operation", "inputs": ["selected OperationRow", "JSON editor text"], "side_effects": ["validates JSON", "starts OperationRunWorker", "disables Run button"], "errors": ["invalid_json", "operation_not_selected", "worker_already_running"], "returns_or_emits": ["progress message"]},
                {"method": "OperationRunWorker.run", "inputs": ["host", "operation_key", "args_json"], "side_effects": ["builds queued payload only", "does not touch UI widgets"], "errors": ["invalid_json", "operation_not_registered"], "returns_or_emits": ["progress", "finished"]},
            ],
            "representative_code": (
                "@dataclass(frozen=True)\n"
                "class OperationRow:\n"
                "    host: str\n"
                "    key: str\n"
                "    label: str\n"
                "    function: str\n"
                "    required: tuple[str, ...] = ()\n"
                "    optional: tuple[str, ...] = ()\n"
                "    mutates_project: bool = False\n\n"
                "    @classmethod\n"
                "    def from_unreal(cls, item: dict[str, Any]) -> 'OperationRow':\n"
                "        return cls('unreal', item['key'], item.get('label', item['key']), item.get('function', ''), tuple(item.get('required') or item.get('required_args') or ()), tuple((item.get('optional') or item.get('optional_args') or {}).keys() if isinstance(item.get('optional') or item.get('optional_args'), dict) else item.get('optional') or item.get('optional_args') or ()), bool(item.get('mutates_project')))\n\n"
                "    @classmethod\n"
                "    def from_dcc(cls, host: str, item: Any) -> 'OperationRow':\n"
                "        required = getattr(item, 'required', getattr(item, 'required_args', ()))\n"
                "        optional = getattr(item, 'optional', getattr(item, 'optional_args', ()))\n"
                "        optional_names = tuple(optional.keys()) if isinstance(optional, dict) else tuple(optional)\n"
                "        return cls(host, item.key, item.label, item.function, tuple(required), optional_names, bool(item.mutates_project))\n\n"
                "class OperationBackend:\n"
                "    def __init__(self, router: Any | None = None):\n"
                "        self.router = router or CommandRouter()\n\n"
                "    def run_operation(self, host: str, operation_key: str, params: dict[str, Any]) -> dict[str, Any]:\n"
                "        try:\n"
                "            if host == 'unreal':\n"
                "                label, ok, result = self.router.execute_unreal_operation(operation_key, params)\n"
                "            elif host in {'maya', 'blender', 'houdini', 'motionbuilder', 'substance_painter', 'unity'} and hasattr(self.router, 'execute_registered_dcc_operation'):\n"
                "                label, ok, result = self.router.execute_registered_dcc_operation(host, operation_key, params)\n"
                "            elif host in {'maya', 'blender', 'houdini', 'motionbuilder', 'substance_painter', 'unity'}:\n"
                "                return {'ok': False, 'error': 'backend_adapter_required', 'host': host, 'operation': operation_key, 'params': params}\n"
                "            else:\n"
                "                return {'ok': False, 'error': 'unknown_host', 'host': host, 'operation': operation_key}\n"
                "            return {'ok': bool(ok), 'label': label, 'result': result, 'host': host, 'operation': operation_key}\n"
                "        except Exception as exc:\n"
                "            return {'ok': False, 'error': 'backend_exception', 'detail': str(exc), 'host': host, 'operation': operation_key}\n\n"
                "class OperationRunWorker(QThread):\n"
                "    progress = Signal(str)\n"
                "    finished = Signal(bool, object)\n\n"
                "    def __init__(self, host: str = '', operation_key: str = '', args_json: str = '', backend: OperationBackend | None = None):\n"
                "        super().__init__()\n"
                "        self.progress = Signal(str)\n"
                "        self.finished = Signal(bool, object)\n"
                "        self.host = host\n"
                "        self.operation_key = operation_key\n"
                "        self.args_json = args_json\n\n"
                "        self.backend = backend or OperationBackend()\n\n"
                "    def run(self):\n"
                "        try:\n"
                "            params = json.loads(self.args_json or '{}')\n"
                "        except json.JSONDecodeError as exc:\n"
                "            self.finished.emit(False, {'error': 'invalid_json', 'detail': str(exc)})\n"
                "            return\n"
                "        self.progress.emit(f'Preparing {self.host}:{self.operation_key}')\n"
                "        if self.host == 'unreal':\n"
                "            payload = unreal_operation_payload(self.operation_key, params)\n"
                "            params = payload['kwargs']\n"
                "        elif self.operation_key not in dcc_operation_registry(self.host):\n"
                "            self.finished.emit(False, {'error': 'operation_not_registered'})\n"
                "            return\n"
                "        result = self.backend.run_operation(self.host, self.operation_key, params)\n"
                "        self.finished.emit(bool(result.get('ok')), result)\n\n"
                "class OperationRunnerPanel(QWidget):\n"
                "    def __init__(self, backend: OperationBackend | None = None):\n"
                "        super().__init__()\n"
                "        self.backend = backend or OperationBackend()\n"
                "        self._rows: list[OperationRow] = []\n"
                "        self.selected_index = 0\n"
                "        self.args_editor = _PlainTextBuffer()\n"
                "        self.result_editor = _PlainTextBuffer()\n"
                "        self.run_button = _ButtonState()\n"
                "        self.worker = None\n"
                "        self.refresh_catalog()\n\n"
                "    def refresh_catalog(self):\n"
                "        rows = [OperationRow.from_unreal(item) for item in operation_catalog()]\n"
                "        for host in ('blender', 'maya'):\n"
                "            rows.extend(OperationRow.from_dcc(host, item) for item in dcc_operation_registry(host).values())\n"
                "        self._set_rows(rows)\n\n"
                "    def _set_rows(self, rows: list[OperationRow]):\n"
                "        self._rows = list(rows)\n"
                "        self.selected_index = 0 if self._rows else -1\n"
                "        if self._rows:\n"
                "            self.populate_args_template()\n"
                "        return len(self._rows)\n\n"
                "    def _selected_row(self) -> OperationRow:\n"
                "        if self.selected_index < 0 or self.selected_index >= len(self._rows):\n"
                "            raise ValueError('operation_not_selected')\n"
                "        return self._rows[self.selected_index]\n\n"
                "    def populate_args_template(self):\n"
                "        row = self._selected_row()\n"
                "        template = {name: '' for name in (*row.required, *row.optional)}\n"
                "        self.args_editor.setPlainText(json.dumps(template, indent=2))\n"
                "        return template\n\n"
                "    def run_selected_operation(self):\n"
                "        row = self._selected_row()\n"
                "        self.run_button.setEnabled(False)\n"
                "        self.worker = OperationRunWorker(row.host, row.key, self.args_editor.toPlainText(), self.backend)\n"
                "        self.worker.progress.connect(self.result_editor.appendPlainText)\n"
                "        self.worker.finished.connect(self._on_finished)\n"
                "        self.worker.start()\n\n"
                "    def _on_finished(self, ok: bool, payload: object):\n"
                "        self.run_button.setEnabled(True)\n"
                "        self.result_editor.setPlainText(json.dumps({'ok': ok, 'result': payload}, indent=2, default=str))\n\n"
                "class _PlainTextBuffer:\n"
                "    def __init__(self):\n"
                "        self.text = ''\n"
                "    def setPlainText(self, text: str):\n"
                "        self.text = text\n"
                "    def appendPlainText(self, text: str):\n"
                "        self.text = f'{self.text}\\n{text}'.strip()\n"
                "    def toPlainText(self) -> str:\n"
                "        return self.text\n\n"
                "class _ButtonState:\n"
                "    def __init__(self):\n"
                "        self.enabled = True\n"
                "    def setEnabled(self, enabled: bool):\n"
                "        self.enabled = bool(enabled)"
            ),
            "integration_points": [
                "Return a standalone OperationRunnerPanel that can be embedded in any host window; only register it in an app tab/menu when the prompt explicitly asks for persistent integration.",
                "Route actual execution through existing DCC/Unreal execution services after payload preview is valid.",
                "Keep UI responsive by disabling Run button while OperationRunWorker is active and appending progress/results via signals.",
            ],
            "repo_grounding": [
                {"purpose": "Qt style source", "source": "code.search_project result matching QWidget/QThread/QPlainTextEdit"},
                {"purpose": "Unreal operation catalog source", "source": "tech_connector.services.unreal.unreal_operation_service.operation_catalog"},
                {"purpose": "DCC registry source", "source": "tech_connector.services.dcc.dcc_operation_service.dcc_operation_registry"},
            ],
            "pre_patch_review": [
                "All referenced imports exist or the patch adds a guarded fallback.",
                "The UI constructs real Qt widgets for search, host filtering, operation selection, argument editing, progress, and result display.",
                "No UI widget is mutated directly from OperationRunWorker.run.",
                "Run button is disabled during active worker execution and re-enabled on finished/error.",
                "Invalid JSON and missing operation selection produce visible errors.",
                "Tests assert catalog loading, JSON template generation, and queued payload creation.",
            ],
            "acceptance_tests": [
                {"name": "loads_unreal_and_dcc_catalog_rows", "asserts": ["operation_catalog called", "dcc_operation_registry called for blender and maya", "rows include host/key/function"]},
                {"name": "builds_json_template_from_selected_operation", "asserts": ["required and optional args are present", "template is valid JSON"]},
                {"name": "invalid_json_does_not_start_host_execution", "asserts": ["finished emits ok=False", "error is invalid_json"]},
                {"name": "unreal_operation_calls_backend_adapter", "asserts": ["unreal_operation_payload validates selected key and params", "CommandRouter.execute_unreal_operation is called through OperationBackend", "result status is backend_called in disposable test"]},
                {"name": "worker_does_not_block_or_touch_widgets", "asserts": ["execution path is in QThread", "UI updates happen through signals"]},
            ],
            "quality_gates": [
                {"gate": "syntax", "tool": "python -m py_compile", "pass_condition": "all changed Python files compile"},
                {"gate": "import", "tool": "focused import test", "pass_condition": "new panel imports with PySide available or cleanly skipped in headless tests"},
                {"gate": "contract", "tool": "unit tests", "pass_condition": "method contracts are covered by focused assertions"},
                {"gate": "ui_threading", "tool": "static review plus unit test", "pass_condition": "worker never mutates QWidget instances directly"},
                {"gate": "dispatch_safety", "tool": "unit tests", "pass_condition": "run operation builds/queues payload and reports host disconnection rather than blocking UI"},
            ],
            "quality_bar": {
                "target_level": "first_try_usable_integrated_tool",
                "current_level": "functional_generated_ui_smoke_validated",
                "confidence": "medium",
                "proven": [
                    "Generated artifact constructs a real QWidget layout with QComboBox host filtering, QLineEdit search, QTableWidget operation selection, QPlainTextEdit JSON arguments, QPushButton execution, and progress/result output.",
                    "Generated artifact has explicit imports for the real Unreal operation catalog, DCC registry, and CommandRouter.",
                    "UI flow is decomposed as panel -> worker -> backend -> CommandRouter.",
                    "Disposable validation can import the generated module, instantiate the panel, build JSON templates, run Unreal and DCC operations through backend adapters, and report invalid JSON.",
                    "Worker contract avoids direct widget mutation and reports results through progress/finished signals.",
                ],
                "not_yet_proven": [
                    "The disposable UI uses headless stand-ins when PySide6 is unavailable, so real rendered QTableWidget visuals are not live-validated in that runtime.",
                    "Host-window embedding is intentionally not performed unless the prompt asks to install the panel into a specific app shell.",
                    "Real host availability/error states need to be exercised against connected Unreal/Maya/Blender sessions before claiming direct execution confidence.",
                ],
                "promotion_requirements": [
                    "Run focused Qt tests in a PySide-capable runtime using qtbot or equivalent interaction helpers.",
                    "Run backend adapter tests against fake bridges and at least one live connected host smoke test.",
                    "Capture readback evidence: selected operation, payload, backend call, result/error text, and host status handling.",
                ],
                "blocks_first_try_claim": True,
            },
            "implementation_risks": [
                {"risk": "PySide may not be installed in headless test runtime", "mitigation": "guard UI tests with import skip while keeping payload/service tests deterministic"},
                {"risk": "operation_catalog return shape may differ from expected dict keys", "mitigation": "normalize through OperationRow.from_unreal with defaults and focused catalog fixture"},
                {"risk": "real execution path may require host status checks", "mitigation": "queue/preview payload first and defer direct host execution to existing execution service"},
            ],
            "readback_plan": [
                "Import OperationRunnerPanel or skip with explicit PySide unavailable reason.",
                "Instantiate panel with mocked operation catalogs.",
                "Select one Unreal operation and verify JSON template/result payload.",
                "Run worker with invalid JSON and verify structured error.",
                "Verify no direct host execution is attempted from the UI thread.",
            ],
        }
        expected_code_payload["representative_code"] = (
            "@dataclass(frozen=True)\n"
            "class OperationRow:\n"
            "    host: str\n"
            "    key: str\n"
            "    label: str\n"
            "    function: str\n"
            "    required: tuple[str, ...] = ()\n"
            "    optional: tuple[str, ...] = ()\n"
            "    mutates_project: bool = False\n\n"
            "    @classmethod\n"
            "    def from_unreal(cls, item: dict[str, Any]) -> 'OperationRow':\n"
            "        optional = item.get('optional') or item.get('optional_args') or ()\n"
            "        optional_names = tuple(optional.keys()) if isinstance(optional, dict) else tuple(optional)\n"
            "        return cls('unreal', item['key'], item.get('label', item['key']), item.get('function', ''), tuple(item.get('required') or item.get('required_args') or ()), optional_names, bool(item.get('mutates_project')))\n\n"
            "    @classmethod\n"
            "    def from_dcc(cls, host: str, item: Any) -> 'OperationRow':\n"
            "        required = getattr(item, 'required', getattr(item, 'required_args', ()))\n"
            "        optional = getattr(item, 'optional', getattr(item, 'optional_args', ()))\n"
            "        optional_names = tuple(optional.keys()) if isinstance(optional, dict) else tuple(optional)\n"
            "        return cls(host, item.key, item.label, item.function, tuple(required), optional_names, bool(item.mutates_project))\n\n"
            "class OperationBackend:\n"
            "    def __init__(self, router: Any | None = None):\n"
            "        self.router = router or CommandRouter()\n\n"
            "    def run_operation(self, host: str, operation_key: str, params: dict[str, Any]) -> dict[str, Any]:\n"
            "        try:\n"
            "            if host == 'unreal':\n"
            "                label, ok, result = self.router.execute_unreal_operation(operation_key, params)\n"
            "            elif host in {'maya', 'blender', 'houdini', 'motionbuilder', 'substance_painter', 'unity'} and hasattr(self.router, 'execute_registered_dcc_operation'):\n"
            "                label, ok, result = self.router.execute_registered_dcc_operation(host, operation_key, params)\n"
            "            elif host in {'maya', 'blender', 'houdini', 'motionbuilder', 'substance_painter', 'unity'}:\n"
            "                return {'ok': False, 'error': 'backend_adapter_required', 'host': host, 'operation': operation_key, 'params': params}\n"
            "            else:\n"
            "                return {'ok': False, 'error': 'unknown_host', 'host': host, 'operation': operation_key}\n"
            "            return {'ok': bool(ok), 'label': label, 'result': result, 'host': host, 'operation': operation_key}\n"
            "        except Exception as exc:\n"
            "            return {'ok': False, 'error': 'backend_exception', 'detail': str(exc), 'host': host, 'operation': operation_key}\n\n"
            "class OperationRunWorker(QThread):\n"
            "    progress = Signal(str)\n"
            "    finished = Signal(bool, object)\n\n"
            "    def __init__(self, host: str = '', operation_key: str = '', args_json: str = '', backend: OperationBackend | None = None):\n"
            "        super().__init__()\n"
            "        self.host = host\n"
            "        self.operation_key = operation_key\n"
            "        self.args_json = args_json\n"
            "        self.backend = backend or OperationBackend()\n\n"
            "    def run(self):\n"
            "        try:\n"
            "            params = json.loads(self.args_json or '{}')\n"
            "        except json.JSONDecodeError as exc:\n"
            "            self.finished.emit(False, {'error': 'invalid_json', 'detail': str(exc)})\n"
            "            return\n"
            "        self.progress.emit(f'Preparing {self.host}:{self.operation_key}')\n"
            "        if self.host == 'unreal':\n"
            "            payload = unreal_operation_payload(self.operation_key, params)\n"
            "            params = payload['kwargs']\n"
            "        elif self.operation_key not in dcc_operation_registry(self.host):\n"
            "            self.finished.emit(False, {'error': 'operation_not_registered'})\n"
            "            return\n"
            "        result = self.backend.run_operation(self.host, self.operation_key, params)\n"
            "        self.finished.emit(bool(result.get('ok')), result)\n\n"
            "class OperationRunnerPanel(QWidget):\n"
            "    def __init__(self, backend: OperationBackend | None = None):\n"
            "        super().__init__()\n"
            "        self.backend = backend or OperationBackend()\n"
            "        self._all_rows: list[OperationRow] = []\n"
            "        self._visible_rows: list[OperationRow] = []\n"
            "        self.worker = None\n"
            "        self.host_filter = QComboBox()\n"
            "        self.host_filter.addItems(['all', 'unreal', 'blender', 'maya'])\n"
            "        self.search_edit = QLineEdit()\n"
            "        self.search_edit.setPlaceholderText('Search operations, labels, functions, args')\n"
            "        self.operation_table = QTableWidget(0, 6)\n"
            "        self.operation_table.setHorizontalHeaderLabels(['Host', 'Operation', 'Label', 'Function', 'Required', 'Mutates'])\n"
            "        self.operation_table.setSelectionBehavior(QTableWidget.SelectRows)\n"
            "        self.operation_table.setSelectionMode(QTableWidget.SingleSelection)\n"
            "        self.args_editor = QPlainTextEdit()\n"
            "        self.args_editor.setPlaceholderText('JSON arguments for the selected operation')\n"
            "        self.run_button = QPushButton('Run / Queue')\n"
            "        self.progress_label = QLabel('Ready')\n"
            "        self.result_editor = QPlainTextEdit()\n"
            "        self.result_editor.setReadOnly(True)\n"
            "        self._build_layout()\n"
            "        self.host_filter.currentTextChanged.connect(self.apply_filters)\n"
            "        self.search_edit.textChanged.connect(self.apply_filters)\n"
            "        self.operation_table.itemSelectionChanged.connect(self.populate_args_template)\n"
            "        self.run_button.clicked.connect(self.run_selected_operation)\n"
            "        self.refresh_catalog()\n\n"
            "    def _build_layout(self):\n"
            "        filters = QHBoxLayout()\n"
            "        filters.addWidget(QLabel('Host'))\n"
            "        filters.addWidget(self.host_filter)\n"
            "        filters.addWidget(QLabel('Search'))\n"
            "        filters.addWidget(self.search_edit, 1)\n"
            "        layout = QVBoxLayout(self)\n"
            "        layout.addLayout(filters)\n"
            "        layout.addWidget(self.operation_table, 2)\n"
            "        layout.addWidget(QLabel('Arguments'))\n"
            "        layout.addWidget(self.args_editor, 1)\n"
            "        layout.addWidget(self.run_button)\n"
            "        layout.addWidget(self.progress_label)\n"
            "        layout.addWidget(self.result_editor, 1)\n\n"
            "    def refresh_catalog(self):\n"
            "        rows = [OperationRow.from_unreal(item) for item in operation_catalog()]\n"
            "        for host in ('blender', 'maya'):\n"
            "            rows.extend(OperationRow.from_dcc(host, item) for item in dcc_operation_registry(host).values())\n"
            "        self._all_rows = rows\n"
            "        self.apply_filters()\n"
            "        return len(rows)\n\n"
            "    def apply_filters(self, *_):\n"
            "        host = self.host_filter.currentText() if hasattr(self.host_filter, 'currentText') else 'all'\n"
            "        query = self.search_edit.text().strip().lower() if hasattr(self.search_edit, 'text') else ''\n"
            "        visible = []\n"
            "        for row in self._all_rows:\n"
            "            haystack = ' '.join([row.host, row.key, row.label, row.function, ' '.join(row.required), ' '.join(row.optional)]).lower()\n"
            "            if host != 'all' and row.host != host:\n"
            "                continue\n"
            "            if query and query not in haystack:\n"
            "                continue\n"
            "            visible.append(row)\n"
            "        self._set_rows(visible)\n"
            "        return len(visible)\n\n"
            "    def _set_rows(self, rows: list[OperationRow]):\n"
            "        self._visible_rows = list(rows)\n"
            "        self.operation_table.setRowCount(len(self._visible_rows))\n"
            "        for index, row in enumerate(self._visible_rows):\n"
            "            values = [row.host, row.key, row.label, row.function, ', '.join(row.required), 'yes' if row.mutates_project else 'no']\n"
            "            for column, value in enumerate(values):\n"
            "                item = QTableWidgetItem(value)\n"
            "                item.setData(Qt.UserRole, row)\n"
            "                self.operation_table.setItem(index, column, item)\n"
            "        if self._visible_rows:\n"
            "            self.operation_table.selectRow(0)\n"
            "            self.populate_args_template()\n"
            "        else:\n"
            "            self.args_editor.setPlainText('{}')\n"
            "        return len(self._visible_rows)\n\n"
            "    def _selected_row(self) -> OperationRow:\n"
            "        index = self.operation_table.currentRow()\n"
            "        if index < 0 or index >= len(self._visible_rows):\n"
            "            raise ValueError('operation_not_selected')\n"
            "        return self._visible_rows[index]\n\n"
            "    def populate_args_template(self):\n"
            "        row = self._selected_row()\n"
            "        template = {name: '' for name in (*row.required, *row.optional)}\n"
            "        self.args_editor.setPlainText(json.dumps(template, indent=2))\n"
            "        return template\n\n"
            "    def run_selected_operation(self):\n"
            "        try:\n"
            "            row = self._selected_row()\n"
            "        except ValueError as exc:\n"
            "            self._on_finished(False, {'error': str(exc)})\n"
            "            return\n"
            "        self.run_button.setEnabled(False)\n"
            "        self.progress_label.setText(f'Queued {row.host}:{row.key}')\n"
            "        self.worker = OperationRunWorker(row.host, row.key, self.args_editor.toPlainText(), self.backend)\n"
            "        self.worker.progress.connect(self.progress_label.setText)\n"
            "        self.worker.finished.connect(self._on_finished)\n"
            "        self.worker.start()\n\n"
            "    def _on_finished(self, ok: bool, payload: object):\n"
            "        self.run_button.setEnabled(True)\n"
            "        self.progress_label.setText('Complete' if ok else 'Failed')\n"
            "        self.result_editor.setPlainText(json.dumps({'ok': ok, 'result': payload}, indent=2, default=str))\n"
        )
    elif wants_rollback_journal:
        expected_code_dependencies = ["project edit transaction scan", "existing write/apply boundaries", "focused rollback recovery tests"]
        expected_code_payload = {
            "expected_files": [
                {"path": "tech_connector/services/project_edit_transaction_service.py", "purpose": "Integrate journal creation, snapshots, and rollback into multi-file edit transactions."},
                {"path": "tech_connector/services/project_edit_rollback_journal_service.py", "purpose": "Typed rollback journal records and recovery helpers."},
                {"path": "examples/tech_connector/tests/test_project_edit_rollback_journal_service.py", "purpose": "Regression coverage for failed write recovery and multi-file rollback."},
            ],
            "expected_imports": ["dataclasses.dataclass", "pathlib.Path", "json", "time", "typing.Any"],
            "expected_classes": [
                {"name": "RollbackJournalEntry", "kind": "dataclass", "fields": ["path", "before_hash", "after_hash", "backup_path", "operation", "timestamp"]},
                {"name": "ProjectEditRollbackJournal", "kind": "service", "methods": ["begin()", "snapshot_file(path)", "record_change(path)", "rollback()", "finalize()"]},
            ],
            "method_contracts": [
                {"method": "ProjectEditRollbackJournal.begin", "inputs": ["transaction id", "project root"], "side_effects": ["creates journal directory", "opens manifest"], "errors": ["journal_path_unwritable"], "returns_or_emits": ["journal id"]},
                {"method": "ProjectEditRollbackJournal.snapshot_file", "inputs": ["Path"], "side_effects": ["copies before image", "records before hash"], "errors": ["path_outside_project", "file_missing"], "returns_or_emits": ["RollbackJournalEntry"]},
                {"method": "ProjectEditRollbackJournal.record_change", "inputs": ["Path"], "side_effects": ["stores after hash", "updates manifest"], "errors": ["snapshot_missing"], "returns_or_emits": ["updated entry"]},
                {"method": "ProjectEditRollbackJournal.rollback", "inputs": ["journal entries"], "side_effects": ["restores backups", "removes newly-created files when safe"], "errors": ["hash_mismatch", "restore_failed"], "returns_or_emits": ["rollback evidence"]},
                {"method": "ProjectEditRollbackJournal.finalize", "inputs": ["validation result"], "side_effects": ["marks journal committed or retained-for-debug"], "errors": [], "returns_or_emits": ["final journal status"]},
            ],
            "representative_code": (
                "@dataclass(frozen=True)\n"
                "class RollbackJournalEntry:\n"
                "    path: str\n"
                "    before_hash: str\n"
                "    after_hash: str = ''\n"
                "    backup_path: str = ''\n\n"
                "class ProjectEditRollbackJournal:\n"
                "    def __init__(self, project_root: Path, journal_root: Path):\n"
                "        self.project_root = project_root.resolve()\n"
                "        self.journal_root = journal_root\n"
                "        self.entries: dict[Path, RollbackJournalEntry] = {}\n\n"
                "    def snapshot_file(self, path: Path) -> RollbackJournalEntry:\n"
                "        target = path.resolve()\n"
                "        if self.project_root not in target.parents and target != self.project_root:\n"
                "            raise ValueError('path_outside_project')\n"
                "        before_hash = _sha256(target) if target.exists() else ''\n"
                "        backup_path = self._backup_path_for(target)\n"
                "        if target.exists():\n"
                "            backup_path.parent.mkdir(parents=True, exist_ok=True)\n"
                "            shutil.copy2(target, backup_path)\n"
                "        entry = RollbackJournalEntry(str(target), before_hash, backup_path=str(backup_path))\n"
                "        self.entries[target] = entry\n"
                "        self._write_manifest()\n"
                "        return entry\n\n"
                "    def record_change(self, path: Path) -> None:\n"
                "        target = path.resolve()\n"
                "        entry = self.entries[target]\n"
                "        self.entries[target] = replace(entry, after_hash=_sha256(target) if target.exists() else '')\n"
                "        self._write_manifest()\n\n"
                "    def rollback(self) -> dict[str, Any]:\n"
                "        restored = []\n"
                "        for target, entry in reversed(self.entries.items()):\n"
                "            if entry.backup_path and Path(entry.backup_path).exists():\n"
                "                shutil.copy2(entry.backup_path, target)\n"
                "            elif target.exists():\n"
                "                target.unlink()\n"
                "            restored.append(str(target))\n"
                "        return {'status': 'rolled_back', 'restored': restored}"
            ),
            "integration_points": [
                "Wrap multi-file project edits before first write.",
                "Record backup paths and hashes before mutation.",
                "On failed write/test validation, restore files from journal and report rollback evidence.",
            ],
            "repo_grounding": [
                {"purpose": "Edit transaction boundary", "source": "code.inspect_symbols result for apply_patch/project edit services"},
                {"purpose": "Existing result shape", "source": "neighboring service functions returning structured dict status"},
                {"purpose": "Test style", "source": "focused unittest modules under examples/tech_connector/tests"},
            ],
            "pre_patch_review": [
                "Every mutated path is resolved under the active project root before snapshot or restore.",
                "Existing files are copied before first write; newly-created files can be removed on rollback.",
                "Manifest writes are deterministic JSON and include before/after hashes.",
                "Rollback returns explicit restored paths and failures.",
                "Tests simulate a failed second write and verify the first file is restored.",
            ],
            "acceptance_tests": [
                {"name": "snapshots_existing_file_before_write", "asserts": ["backup exists", "before hash matches original"]},
                {"name": "rolls_back_after_failed_second_write", "asserts": ["first file restored", "new file removed or marked", "failure evidence returned"]},
                {"name": "rejects_paths_outside_project", "asserts": ["ValueError path_outside_project", "no backup written"]},
                {"name": "manifest_is_deterministic_json", "asserts": ["entries include path/before_hash/after_hash/backup_path", "stable ordering"]},
            ],
            "quality_gates": [
                {"gate": "syntax", "tool": "python -m py_compile", "pass_condition": "rollback journal service and transaction integration compile"},
                {"gate": "path_safety", "tool": "unit tests", "pass_condition": "outside-root paths are rejected before filesystem mutation"},
                {"gate": "rollback_integrity", "tool": "unit tests", "pass_condition": "hashes and restored file contents match pre-write state"},
                {"gate": "transaction_integration", "tool": "focused service tests", "pass_condition": "failed write invokes rollback and reports evidence"},
            ],
            "implementation_risks": [
                {"risk": "existing edit service may not have a single transaction boundary", "mitigation": "wrap the narrowest common apply/write function discovered by code.inspect_symbols"},
                {"risk": "newly-created files need different rollback semantics than modified files", "mitigation": "record missing before_hash and remove only paths created inside project root"},
            ],
            "readback_plan": [
                "Create a temporary project root fixture.",
                "Snapshot, mutate, and record one existing file.",
                "Simulate a later failed write.",
                "Run rollback and compare restored contents and hashes.",
                "Inspect journal manifest for deterministic recovery evidence.",
            ],
        }
    elif wants_prompt_router_evidence:
        expected_code_dependencies = ["prompt router scan", "evidence ranking scan", "deterministic fuzz fixture contract"]
        expected_code_payload = {
            "expected_files": [
                {"path": "tech_connector/services/prompt/prompt_route_service.py", "purpose": "Emit deterministic route evidence and ambiguity metadata."},
                {"path": "tech_connector/services/reasoning/evidence_ranking_service.py", "purpose": "Return structured attribution paths for target ranking."},
                {"path": "examples/tech_connector/tests/fixtures/prompt_route_fuzz_cases.json", "purpose": "Deterministic fuzz regression corpus."},
                {"path": "examples/tech_connector/tests/test_prompt_route_fuzz_corpus.py", "purpose": "Stable regression tests for fuzzy prompt routing."},
            ],
            "expected_imports": ["dataclasses.dataclass", "json", "typing.Any"],
            "expected_classes": [
                {"name": "RouteEvidence", "kind": "dataclass", "fields": ["route", "score", "signals", "ambiguity"]},
                {"name": "AttributionPath", "kind": "dataclass", "fields": ["type", "source", "query_fragment", "evidence", "weight"]},
                {"name": "PromptRouteFuzzCase", "kind": "fixture schema", "fields": ["seed", "mutation", "expected_route", "expected_signals"]},
            ],
            "method_contracts": [
                {"method": "load_prompt_route_fuzz_cases", "inputs": ["fixture path"], "side_effects": [], "errors": ["invalid_fixture_schema"], "returns_or_emits": ["PromptRouteFuzzCase list"]},
                {"method": "route_with_evidence", "inputs": ["prompt text"], "side_effects": [], "errors": ["empty_prompt"], "returns_or_emits": ["RouteEvidence"]},
                {"method": "rank_target_with_attributions", "inputs": ["query", "candidate targets", "active context"], "side_effects": [], "errors": [], "returns_or_emits": ["ranked targets with AttributionPath list"]},
                {"method": "test_fuzz_corpus_routes", "inputs": ["deterministic fixture corpus"], "side_effects": [], "errors": ["route mismatch", "missing required evidence signal"], "returns_or_emits": ["stable regression result"]},
            ],
            "representative_code": (
                "@dataclass(frozen=True)\n"
                "class RouteEvidence:\n"
                "    route: str\n"
                "    score: float\n"
                "    signals: dict[str, Any]\n"
                "    ambiguity: dict[str, Any]\n\n"
                "@dataclass(frozen=True)\n"
                "class AttributionPath:\n"
                "    type: str\n"
                "    source: str\n"
                "    query_fragment: str\n"
                "    evidence: str\n"
                "    weight: float\n\n"
                "@dataclass(frozen=True)\n"
                "class PromptRouteFuzzCase:\n"
                "    seed: str\n"
                "    mutation: str\n"
                "    expected_route: str\n"
                "    expected_signals: tuple[str, ...]\n\n"
                "def route_with_evidence(prompt: str) -> RouteEvidence:\n"
                "    signals = collect_route_signals(prompt)\n"
                "    evidence = rank_route_candidates(signals)\n"
                "    return RouteEvidence(route=evidence.route, score=evidence.score, signals=signals, ambiguity=evidence.ambiguity)\n\n"
                "def load_prompt_route_fuzz_cases(path: Path) -> list[PromptRouteFuzzCase]:\n"
                "    raw_cases = json.loads(path.read_text(encoding='utf-8'))\n"
                "    return [PromptRouteFuzzCase(**item) for item in raw_cases]\n\n"
                "def rank_target_with_attributions(query: str, candidates: list[Any], context: dict[str, Any]) -> list[Any]:\n"
                "    ranked = []\n"
                "    for candidate in candidates:\n"
                "        attributions = collect_attribution_paths(query, candidate, context)\n"
                "        ranked.append(with_score(candidate, sum(path.weight for path in attributions), attributions))\n"
                "    return sorted(ranked, key=lambda item: item.score, reverse=True)"
            ),
            "integration_points": [
                "Keep fuzz generation optional; promote reviewed mutations into the deterministic fixture.",
                "Expose top attribution paths in route metadata and compact planner output.",
                "Assert both selected route and defensible evidence in tests.",
            ],
            "repo_grounding": [
                {"purpose": "Router implementation", "source": "tech_connector/services/prompt/prompt_route_service.py"},
                {"purpose": "Ranking implementation", "source": "tech_connector/services/reasoning/evidence_ranking_service.py"},
                {"purpose": "Regression corpus", "source": "examples/tech_connector/tests/fixtures/prompt_route_fuzz_cases.json"},
            ],
            "pre_patch_review": [
                "Ollama/generated fuzzing is optional and never required for normal deterministic tests.",
                "Fixture cases include seed, mutation, expected route, and required evidence signals.",
                "Attribution paths are structured data, not prose-only explanations.",
                "UI/debug renderers consume the same attribution payload used by tests.",
                "Tests assert both selected route and at least one defensible attribution signal.",
            ],
            "acceptance_tests": [
                {"name": "deterministic_fuzz_corpus_routes", "asserts": ["each mutation yields expected route", "no network or Ollama dependency"]},
                {"name": "route_evidence_contains_required_signals", "asserts": ["signals include matched trigger/source", "ambiguity is explicit"]},
                {"name": "target_ranking_returns_attribution_paths", "asserts": ["top target includes semantic/open-tab/cursor paths when available"]},
                {"name": "weak_signals_are_debug_only", "asserts": ["compact UI payload limits top reasons", "full trace remains available"]},
            ],
            "quality_gates": [
                {"gate": "determinism", "tool": "unit tests", "pass_condition": "fixture tests pass repeatedly without model calls"},
                {"gate": "schema", "tool": "fixture validation test", "pass_condition": "all fuzz cases and attribution paths match schema"},
                {"gate": "explainability", "tool": "route/ranking tests", "pass_condition": "selected route/target has at least one defensible attribution"},
                {"gate": "performance", "tool": "timed focused tests", "pass_condition": "corpus route test stays under local timeout budget"},
            ],
            "implementation_risks": [
                {"risk": "attribution payload can become noisy", "mitigation": "store full trace but expose top weighted reasons by default"},
                {"risk": "fuzz generator nondeterminism can poison CI", "mitigation": "keep generator optional and promote reviewed cases into checked-in corpus"},
            ],
            "readback_plan": [
                "Load deterministic fuzz fixture corpus.",
                "Route each mutation and assert expected route plus required evidence signals.",
                "Rank sample blueprint targets and assert structured AttributionPath output.",
                "Render compact trace payload and verify top reasons are bounded.",
            ],
        }
    else:
        expected_code_dependencies = ["code.search_project output", "code.inspect_symbols output", "existing service/test conventions"]
        expected_code_payload = {
            "expected_files": [
                {"path": "resolved source module from code.inspect_symbols", "purpose": "Implement the requested behavior in the owning module."},
                {"path": "resolved focused test module from code.inspect_symbols", "purpose": "Prove the requested behavior and edge case."},
            ],
            "expected_imports": ["imports resolved from existing module patterns"],
            "expected_classes": [
                {"name": "ResolvedImplementationUnit", "kind": "function/class/service", "methods": ["inspect current contract", "apply scoped behavior", "return structured result"]},
            ],
            "method_contracts": [
                {"method": "resolved_entrypoint", "inputs": ["requested behavior", "resolved project context"], "side_effects": ["only scoped file changes from patch plan"], "errors": ["missing_target", "ambiguous_contract", "validation_failed"], "returns_or_emits": ["structured result"]},
                {"method": "focused_regression_test", "inputs": ["requested behavior", "edge case"], "side_effects": [], "errors": ["assertion mismatch"], "returns_or_emits": ["deterministic test proof"]},
            ],
            "representative_code": (
                "def requested_behavior_entrypoint(...):\n"
                "    current = inspect_existing_state(...)\n"
                "    result = apply_scoped_change(current, ...)\n"
                "    return validate_and_report(result)"
            ),
            "integration_points": ["Use existing service boundaries and focused tests discovered by code.inspect_symbols."],
            "repo_grounding": [
                {"purpose": "Source ownership", "source": "code.inspect_symbols result for target module"},
                {"purpose": "Call contract", "source": "callers and tests discovered before patching"},
            ],
            "pre_patch_review": [
                "Target file, owner symbol, and focused test file are resolved before writing.",
                "All planned imports are already present nearby or explicitly added.",
                "The representative code has no ellipsis in the final patch plan.",
                "Validation command list is specific enough to run without broad discovery.",
            ],
            "acceptance_tests": [
                {"name": "focused_behavior_regression", "asserts": ["requested behavior succeeds", "main edge case is covered"]},
                {"name": "unchanged_contracts_remain_compatible", "asserts": ["existing callers/tests still pass"]},
            ],
            "quality_gates": [
                {"gate": "syntax", "tool": "python -m py_compile", "pass_condition": "changed Python files compile"},
                {"gate": "focused_tests", "tool": "python -m unittest or project runner", "pass_condition": "focused regression tests pass"},
                {"gate": "patch_scope", "tool": "changed-file review", "pass_condition": "changed files match patch plan"},
            ],
            "quality_bar": {
                "target_level": "first_try_usable_generated_code",
                "current_level": "planned_code_with_pre_patch_validation",
                "confidence": "medium",
                "proven": [
                    "Plan includes expected files, imports, classes/method contracts, representative code, and focused acceptance tests.",
                    "Generated code must pass code.validate_expected_code before patching.",
                    "Patch must be applied and imported in a disposable workspace before it can be marked truly passing.",
                ],
                "not_yet_proven": [
                    "No live DCC/editor host smoke has run unless the host bridge is connected.",
                    "Real UI rendering is only proven after a PySide/host-capable runtime test.",
                ],
                "promotion_requirements": [
                    "Run generated patch validation in a temp workspace.",
                    "Run focused tests and host smoke/readback where applicable.",
                    "Capture exact output, errors, and rollback instructions.",
                ],
                "blocks_first_try_claim": True,
            },
            "implementation_risks": [
                {"risk": "generic code prompt may still be under-specified", "mitigation": "block patch if target file/symbol/test cannot be resolved"},
            ],
            "readback_plan": [
                "Inspect resolved source and test files.",
                "Apply patch only after imports and owner symbols are known.",
                "Run syntax and focused tests.",
                "Report remaining ambiguity or validation failures with exact paths.",
            ],
        }
    common = {
        "callable": action_type,
        "implementation_status": "registered_or_adapter_required",
        "capability": capability,
        "host": host,
        "source_prompt": prompt,
        "required_context": [
            "active project root",
            "focused target resolution",
            "operation registry entry",
            "rollback/validation policy",
        ],
        "arguments": {},
        "dependencies": [],
        "expected_outputs": [],
        "readback_validation": list(item.get("validates_with") or []),
        "fallback": "stop and report missing callable, target, permission, or validation evidence before execution",
    }
    plans: dict[str, dict[str, Any]] = {
        "code.search_project": {
            "callable": "tech_connector.services.code_operation_service.search_project",
            "implementation_status": "registered_operation",
            "arguments": {
                "root": "active project root",
                "search_terms": (
                    [
                        "QWidget",
                        "QThread",
                        "Signal",
                        "QPlainTextEdit",
                        "QTableWidget",
                        "operation_catalog",
                        "dcc_operation_registry",
                        "unreal_operation_payload",
                    ]
                    if wants_qt_operation_runner
                    else [
                        "rollback journal",
                        "prompt router",
                        "fuzz regression",
                        "attribution paths",
                        "service tests",
                    ]
                ),
                "file_globs": ["*.py", "*.json", "*.md"],
                "exclude_globs": ["**/.*/**", "**/__pycache__/**", "**/*.sqlite", "**/*.sqlite-*"],
                "prompt": prompt,
            },
            "dependencies": ["project root", "file index or rg-compatible search"],
            "expected_outputs": ["candidate source files", "candidate test files", "matched terms"],
        },
        "code.inspect_symbols": {
            "callable": "tech_connector.services.code_operation_service.inspect_symbols",
            "implementation_status": "registered_operation",
            "arguments": {
                "source_files": "candidate files from code.search_project",
                "symbol_queries": (
                    [
                        "OperationRunnerPanel",
                        "QWidget/QDialog tab panels",
                        "QThread worker patterns",
                        "operation_catalog",
                        "dcc_operation_registry",
                        "unreal_operation_payload",
                        "DccExecutionRequest",
                    ]
                    if wants_qt_operation_runner
                    else ["service classes", "route/planner functions", "test cases", "dataclasses/contracts"]
                ),
                "include_callers": True,
                "include_tests": True,
            },
            "dependencies": ["code.search_project output", "AST/symbol index or direct file reads"],
            "expected_outputs": ["symbols", "call sites", "existing behavior summary", "test target list"],
        },
        "code.plan_patch": {
            "callable": "tech_connector.services.code_operation_service.plan_patch",
            "implementation_status": "registered_operation",
            "arguments": {
                "requested_behavior": prompt,
                "target_files": (
                    [
                        "tech_connector/ui/operation_runner_panel.py",
                        "tech_connector/app/main_window_ui.py or existing tab registration module",
                        "examples/tech_connector/tests/test_operation_runner_panel.py",
                    ]
                    if wants_qt_operation_runner
                    else "resolved from code.inspect_symbols"
                ),
                "edit_policy": "scoped patch only; preserve unrelated user changes",
                "rollback_policy": "record changed files and validation command before mutation",
                "ui_contract": (
                    {
                        "widget": "OperationRunnerPanel(QWidget)",
                        "worker": "OperationRunWorker(QThread)",
                        "controls": ["host combo", "search field", "operation table", "JSON args editor", "run/queue button", "progress/result output"],
                        "non_blocking": "all execution/queue preparation goes through QThread signals",
                        "dispatch": ["unreal_operation_payload", "dcc_operation_registry", "DccExecutionRequest or existing route handler"],
                    }
                    if wants_qt_operation_runner
                    else {}
                ),
            },
            "dependencies": ["code.inspect_symbols output", "current file contents"],
            "expected_outputs": ["patch plan", "changed file list", "validation command list"],
        },
        "code.plan_expected_code": {
            "callable": "tech_connector.services.code_operation_service.plan_expected_code",
            "implementation_status": "registered_operation",
            "arguments": {
                "requested_behavior": prompt,
                **expected_code_payload,
            },
            "dependencies": expected_code_dependencies,
            "expected_outputs": ["expected code artifact", "file/class/method plan", "representative implementation skeleton"],
        },
        "code.validate_expected_code": {
            "callable": "tech_connector.services.code_operation_service.validate_expected_code",
            "implementation_status": "registered_operation",
            "arguments": {
                "representative_code": expected_code_payload.get("representative_code", ""),
                "expected_classes": expected_code_payload.get("expected_classes", []),
                "method_contracts": expected_code_payload.get("method_contracts", []),
                "quality_gates": expected_code_payload.get("quality_gates", []),
                "acceptance_tests": expected_code_payload.get("acceptance_tests", []),
                "executable_fixture_code": (
                    "class Signal:\n"
                    "    def __init__(self, *args):\n"
                    "        self.events = []\n"
                    "        self.callbacks = []\n"
                    "    def emit(self, *args):\n"
                    "        self.events.append(args)\n"
                    "        for callback in self.callbacks:\n"
                    "            callback(*args)\n"
                    "    def connect(self, callback):\n"
                    "        self.callbacks.append(callback)\n\n"
                    "class QThread:\n"
                    "    def start(self):\n"
                    "        self.run()\n\n"
                    "    def wait(self, timeout=0):\n"
                    "        return True\n\n"
                    "class Qt:\n"
                    "    UserRole = 32\n\n"
                    "class QWidget:\n"
                    "    def __init__(self, *args):\n"
                    "        self.layout = None\n\n"
                    "class QHBoxLayout:\n"
                    "    def __init__(self, *args):\n"
                    "        self.children = []\n"
                    "    def addWidget(self, widget, *args):\n"
                    "        self.children.append(widget)\n"
                    "    def addLayout(self, layout, *args):\n"
                    "        self.children.append(layout)\n\n"
                    "class QVBoxLayout(QHBoxLayout):\n"
                    "    pass\n\n"
                    "class QLabel:\n"
                    "    def __init__(self, text=''):\n"
                    "        self._text = text\n"
                    "    def setText(self, text):\n"
                    "        self._text = text\n"
                    "    def text(self):\n"
                    "        return self._text\n\n"
                    "class QComboBox:\n"
                    "    def __init__(self):\n"
                    "        self.items = []\n"
                    "        self.index = 0\n"
                    "        self.currentTextChanged = Signal(str)\n"
                    "    def addItems(self, items):\n"
                    "        self.items.extend(items)\n"
                    "    def currentText(self):\n"
                    "        return self.items[self.index] if self.items else ''\n"
                    "    def setCurrentText(self, text):\n"
                    "        if text in self.items:\n"
                    "            self.index = self.items.index(text)\n"
                    "            self.currentTextChanged.emit(text)\n\n"
                    "class QLineEdit:\n"
                    "    def __init__(self):\n"
                    "        self._text = ''\n"
                    "        self.textChanged = Signal(str)\n"
                    "    def setPlaceholderText(self, text):\n"
                    "        self.placeholder = text\n"
                    "    def setText(self, text):\n"
                    "        self._text = text\n"
                    "        self.textChanged.emit(text)\n"
                    "    def text(self):\n"
                    "        return self._text\n\n"
                    "class QPlainTextEdit:\n"
                    "    def __init__(self):\n"
                    "        self._text = ''\n"
                    "        self.read_only = False\n"
                    "    def setPlaceholderText(self, text):\n"
                    "        self.placeholder = text\n"
                    "    def setReadOnly(self, value):\n"
                    "        self.read_only = bool(value)\n"
                    "    def setPlainText(self, text):\n"
                    "        self._text = text\n"
                    "    def appendPlainText(self, text):\n"
                    "        self._text = f'{self._text}\\n{text}'.strip()\n"
                    "    def toPlainText(self):\n"
                    "        return self._text\n\n"
                    "class QPushButton:\n"
                    "    def __init__(self, text=''):\n"
                    "        self.text = text\n"
                    "        self.enabled = True\n"
                    "        self.clicked = Signal()\n"
                    "    def setEnabled(self, enabled):\n"
                    "        self.enabled = bool(enabled)\n"
                    "    def isEnabled(self):\n"
                    "        return self.enabled\n\n"
                    "class QTableWidgetItem:\n"
                    "    def __init__(self, text=''):\n"
                    "        self._text = text\n"
                    "        self.data_values = {}\n"
                    "    def text(self):\n"
                    "        return self._text\n"
                    "    def setData(self, role, value):\n"
                    "        self.data_values[role] = value\n"
                    "    def data(self, role):\n"
                    "        return self.data_values.get(role)\n\n"
                    "class QTableWidget:\n"
                    "    SelectRows = 1\n"
                    "    SingleSelection = 1\n"
                    "    def __init__(self, rows=0, columns=0):\n"
                    "        self.rows = rows\n"
                    "        self.columns = columns\n"
                    "        self.items = {}\n"
                    "        self.current_row = -1\n"
                    "        self.itemSelectionChanged = Signal()\n"
                    "    def setHorizontalHeaderLabels(self, labels):\n"
                    "        self.headers = list(labels)\n"
                    "    def setSelectionBehavior(self, mode):\n"
                    "        self.selection_behavior = mode\n"
                    "    def setSelectionMode(self, mode):\n"
                    "        self.selection_mode = mode\n"
                    "    def setRowCount(self, count):\n"
                    "        self.rows = count\n"
                    "    def setItem(self, row, column, item):\n"
                    "        self.items[(row, column)] = item\n"
                    "    def selectRow(self, row):\n"
                    "        self.current_row = row\n"
                    "        self.itemSelectionChanged.emit()\n"
                    "    def currentRow(self):\n"
                    "        return self.current_row\n\n"
                    "def operation_catalog():\n"
                    "    return [{'key': 'blueprint.scan', 'label': 'Scan Blueprint', 'function': 'unreal_tools.blueprint.scan', 'required_args': ['asset_path'], 'optional_args': [], 'mutates_project': False}]\n\n"
                    "class DccOperation:\n"
                    "    key = 'blender.scan_animation'\n"
                    "    label = 'Scan Blender Animation'\n"
                    "    function = 'tech_connector.services.dcc.dcc_operation_service.blender.scan_animation'\n"
                    "    required_args = ('armature_name',)\n"
                    "    optional_args = ()\n"
                    "    mutates_project = False\n\n"
                    "def dcc_operation_registry(host):\n"
                    "    return {'blender.scan_animation': DccOperation()}\n\n"
                    "def unreal_operation_payload(operation_key, params):\n"
                    "    return {'operation': operation_key, 'kwargs': params}\n\n"
                    "class CommandRouter:\n"
                    "    def __init__(self):\n"
                    "        self.calls = []\n"
                    "    def execute_unreal_operation(self, operation_key, params):\n"
                    "        self.calls.append(('unreal', operation_key, params))\n"
                    "        return 'Fake Unreal Backend', True, {'status': 'backend_called', 'operation': operation_key, 'params': params}\n"
                    "    def execute_registered_dcc_operation(self, host, operation_key, params):\n"
                    "        self.calls.append((host, operation_key, params))\n"
                    "        return f'{host.title()} Backend', True, {'status': 'dcc_backend_called', 'host': host, 'operation': operation_key, 'params': params}\n"
                    if wants_qt_operation_runner
                    else ""
                ),
                "smoke_test_code": (
                    "row = OperationRow.from_unreal(operation_catalog()[0])\n"
                    "assert row.host == 'unreal'\n"
                    "worker = OperationRunWorker()\n"
                    "worker.host = 'unreal'\n"
                    "worker.operation_key = 'blueprint.scan'\n"
                    "worker.args_json = '{\"asset_path\": \"/Game/Test/BP_Test\"}'\n"
                    "worker_results = []\n"
                    "worker.finished.connect(lambda ok, payload: worker_results.append((ok, payload)))\n"
                    "worker.run()\n"
                    "assert worker_results[-1][0] is True\n"
                    "assert worker_results[-1][1]['result']['status'] == 'backend_called'\n"
                    "bad_worker = OperationRunWorker()\n"
                    "bad_worker.host = 'unreal'\n"
                    "bad_worker.operation_key = 'blueprint.scan'\n"
                    "bad_worker.args_json = '{bad json}'\n"
                    "bad_results = []\n"
                    "bad_worker.finished.connect(lambda ok, payload: bad_results.append((ok, payload)))\n"
                    "bad_worker.run()\n"
                    "assert bad_results[-1][0] is False\n"
                    "assert bad_results[-1][1]['error'] == 'invalid_json'\n"
                    "panel = OperationRunnerPanel()\n"
                    "assert len(panel._visible_rows) >= 1\n"
                    "panel.search_edit.setText('blueprint')\n"
                    "assert panel.apply_filters() == 1\n"
                    "template = panel.populate_args_template()\n"
                    "assert 'asset_path' in template\n"
                    "panel.args_editor.setPlainText('{\"asset_path\": \"/Game/Test/BP_Test\"}')\n"
                    "panel.run_selected_operation()\n"
                    "panel.worker.wait(5000)\n"
                    "assert panel.run_button.isEnabled() is True\n"
                    "assert 'backend_called' in panel.result_editor.toPlainText()\n"
                    "panel.search_edit.setText('')\n"
                    "panel.host_filter.setCurrentText('blender')\n"
                    "assert panel.apply_filters() == 1\n"
                    "panel.operation_table.selectRow(0)\n"
                    "template = panel.populate_args_template()\n"
                    "assert 'armature_name' in template\n"
                    "panel.args_editor.setPlainText('{\"armature_name\": \"MannyRig\"}')\n"
                    "panel.run_selected_operation()\n"
                    "panel.worker.wait(5000)\n"
                    "assert 'dcc_backend_called' in panel.result_editor.toPlainText()\n"
                    if wants_qt_operation_runner
                    else ""
                ),
                "allow_exec": wants_qt_operation_runner,
            },
            "dependencies": ["code.plan_expected_code output", "safe disposable fixture for generated code"],
            "expected_outputs": ["static validation result", "mocked smoke test result when available", "quality gate evidence"],
        },
        "code.validate_patch_in_temp_workspace": {
            "callable": "tech_connector.services.code_operation_service.validate_patch_in_temp_workspace",
            "implementation_status": "registered_operation",
            "arguments": {
                "source_root": ".",
                "expected_files": expected_code_payload.get("expected_files", []),
                "patch_files": (
                    [
                        {
                            "path": "tech_connector/ui/operation_runner_panel.py",
                            "content": (
                                "from __future__ import annotations\n\n"
                                "import json\n"
                                "from dataclasses import dataclass\n"
                                "from typing import Any\n\n"
                                "try:\n"
                                "    from PySide6.QtCore import Qt, QThread, Signal\n"
                                "    from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget\n"
                                "except Exception:\n"
                                "    class Qt:\n"
                                "        UserRole = 32\n"
                                "    class Signal:\n"
                                "        def __init__(self, *args):\n"
                                "            self.events = []\n"
                                "            self.callbacks = []\n"
                                "        def emit(self, *args):\n"
                                "            self.events.append(args)\n"
                                "            for callback in self.callbacks:\n"
                                "                callback(*args)\n"
                                "        def connect(self, callback):\n"
                                "            self.callbacks.append(callback)\n"
                                "    class QThread:\n"
                                "        def start(self):\n"
                                "            self.run()\n"
                                "        def wait(self, timeout=0):\n"
                                "            return True\n"
                                "    class QWidget:\n"
                                "        def __init__(self, *args):\n"
                                "            self.layout = None\n\n"
                                "    class QComboBox:\n"
                                "        def __init__(self):\n"
                                "            self.items = []\n"
                                "            self.index = 0\n"
                                "            self.currentTextChanged = Signal(str)\n"
                                "        def addItems(self, items):\n"
                                "            self.items.extend(items)\n"
                                "        def currentText(self):\n"
                                "            return self.items[self.index] if self.items else ''\n"
                                "        def setCurrentText(self, text):\n"
                                "            if text in self.items:\n"
                                "                self.index = self.items.index(text)\n"
                                "                self.currentTextChanged.emit(text)\n"
                                "    class QHBoxLayout:\n"
                                "        def __init__(self, *args):\n"
                                "            self.children = []\n"
                                "        def addWidget(self, widget, *args):\n"
                                "            self.children.append(widget)\n"
                                "        def addLayout(self, layout, *args):\n"
                                "            self.children.append(layout)\n"
                                "    class QLabel:\n"
                                "        def __init__(self, text=''):\n"
                                "            self._text = text\n"
                                "        def setText(self, text):\n"
                                "            self._text = text\n"
                                "        def text(self):\n"
                                "            return self._text\n"
                                "    class QLineEdit:\n"
                                "        def __init__(self):\n"
                                "            self._text = ''\n"
                                "            self.textChanged = Signal(str)\n"
                                "        def setPlaceholderText(self, text):\n"
                                "            self.placeholder = text\n"
                                "        def setText(self, text):\n"
                                "            self._text = text\n"
                                "            self.textChanged.emit(text)\n"
                                "        def text(self):\n"
                                "            return self._text\n"
                                "    class QPlainTextEdit:\n"
                                "        def __init__(self):\n"
                                "            self._text = ''\n"
                                "        def setPlaceholderText(self, text):\n"
                                "            self.placeholder = text\n"
                                "        def setReadOnly(self, value):\n"
                                "            self.read_only = bool(value)\n"
                                "        def setPlainText(self, text):\n"
                                "            self._text = text\n"
                                "        def appendPlainText(self, text):\n"
                                "            self._text = f'{self._text}\\n{text}'.strip()\n"
                                "        def toPlainText(self):\n"
                                "            return self._text\n"
                                "    class QPushButton:\n"
                                "        def __init__(self, text=''):\n"
                                "            self.text = text\n"
                                "            self.enabled = True\n"
                                "            self.clicked = Signal()\n"
                                "        def setEnabled(self, enabled):\n"
                                "            self.enabled = bool(enabled)\n"
                                "        def isEnabled(self):\n"
                                "            return self.enabled\n"
                                "    class QTableWidget:\n"
                                "        SelectRows = 1\n"
                                "        SingleSelection = 1\n"
                                "        def __init__(self, rows=0, columns=0):\n"
                                "            self.rows = rows\n"
                                "            self.columns = columns\n"
                                "            self.items = {}\n"
                                "            self.current_row = -1\n"
                                "            self.itemSelectionChanged = Signal()\n"
                                "        def setHorizontalHeaderLabels(self, labels):\n"
                                "            self.headers = list(labels)\n"
                                "        def setSelectionBehavior(self, mode):\n"
                                "            self.selection_behavior = mode\n"
                                "        def setSelectionMode(self, mode):\n"
                                "            self.selection_mode = mode\n"
                                "        def setRowCount(self, count):\n"
                                "            self.rows = count\n"
                                "        def setItem(self, row, column, item):\n"
                                "            self.items[(row, column)] = item\n"
                                "        def selectRow(self, row):\n"
                                "            self.current_row = row\n"
                                "            self.itemSelectionChanged.emit()\n"
                                "        def currentRow(self):\n"
                                "            return self.current_row\n"
                                "    class QTableWidgetItem:\n"
                                "        def __init__(self, text=''):\n"
                                "            self._text = text\n"
                                "            self.data_values = {}\n"
                                "        def text(self):\n"
                                "            return self._text\n"
                                "        def setData(self, role, value):\n"
                                "            self.data_values[role] = value\n"
                                "        def data(self, role):\n"
                                "            return self.data_values.get(role)\n"
                                "    class QVBoxLayout:\n"
                                "        def __init__(self, *args):\n"
                                "            self.children = []\n"
                                "        def addWidget(self, widget, *args):\n"
                                "            self.children.append(widget)\n"
                                "        def addLayout(self, layout, *args):\n"
                                "            self.children.append(layout)\n\n"
                                "from tech_connector.services.unreal.unreal_operation_service import operation_catalog, unreal_operation_payload\n"
                                "from tech_connector.services.dcc.dcc_operation_service import dcc_operation_registry\n"
                                "from tech_connector.router.command_router import CommandRouter\n\n"
                                f"{expected_code_payload.get('representative_code', '')}\n"
                            ),
                        },
                        {
                            "path": "tech_connector/services/unreal/unreal_operation_service.py",
                            "content": (
                                "def operation_catalog():\n"
                                "    return [{'key': 'blueprint.scan', 'label': 'Scan Blueprint', 'function': 'unreal_tools.blueprint.scan', 'required': ['asset_path'], 'optional': {}, 'mutates_project': False}]\n\n"
                                "def unreal_operation_payload(operation_key, params):\n"
                                "    if operation_key != 'blueprint.scan':\n"
                                "        raise ValueError('unknown operation')\n"
                                "    if not params.get('asset_path'):\n"
                                "        raise ValueError('asset_path required')\n"
                                "    return {'operation': operation_key, 'kwargs': dict(params)}\n"
                            ),
                        },
                        {
                            "path": "tech_connector/services/dcc/dcc_operation_service.py",
                            "content": (
                                "from dataclasses import dataclass\n\n"
                                "@dataclass(frozen=True)\n"
                                "class DccOperation:\n"
                                "    key: str\n"
                                "    label: str\n"
                                "    function: str\n"
                                "    required: tuple[str, ...] = ()\n"
                                "    optional: dict = None\n"
                                "    mutates_project: bool = False\n\n"
                                "def dcc_operation_registry(host):\n"
                                "    if host == 'blender':\n"
                                "        return {'blender.scan_animation': DccOperation('blender.scan_animation', 'Scan Blender Animation', 'tech_connector.services.dcc.dcc_operation_service.blender.scan_animation', ('armature_name',), {}, False)}\n"
                                "    if host == 'maya':\n"
                                "        return {'maya.scan_facial_rig': DccOperation('maya.scan_facial_rig', 'Scan Maya Facial Rig', 'ai_studio.maya.generated.maya_scan_facial_rig', (), {}, False)}\n"
                                "    return {}\n"
                            ),
                        },
                        {
                            "path": "tech_connector/router/command_router.py",
                            "content": (
                                "class CommandRouter:\n"
                                "    def __init__(self):\n"
                                "        self.calls = []\n"
                                "    def execute_unreal_operation(self, operation_key, params):\n"
                                "        self.calls.append(('unreal', operation_key, params))\n"
                                "        return 'Fake Unreal Backend', True, {'status': 'backend_called', 'operation': operation_key, 'params': params}\n"
                                "    def execute_registered_dcc_operation(self, host, operation_key, params):\n"
                                "        self.calls.append((host, operation_key, params))\n"
                                "        return f'{host.title()} Backend', True, {'status': 'dcc_backend_called', 'host': host, 'operation': operation_key, 'params': params}\n"
                            ),
                        },
                        {
                            "path": "examples/tech_connector/tests/test_operation_runner_panel.py",
                            "content": (
                                "import os\n"
                                "import unittest\n\n"
                                "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n\n"
                                "from PySide6.QtWidgets import QApplication\n"
                                "from tech_connector.ui.operation_runner_panel import OperationRow, OperationRunWorker, OperationRunnerPanel, operation_catalog\n\n"
                                "class TestOperationRunnerPanel(unittest.TestCase):\n"
                                "    @classmethod\n"
                                "    def setUpClass(cls):\n"
                                "        cls.app = QApplication.instance() or QApplication([])\n\n"
                                "    def test_worker_builds_unreal_payload_and_reports_invalid_json(self):\n"
                                "        row = OperationRow.from_unreal(operation_catalog()[0])\n"
                                "        self.assertEqual(row.host, 'unreal')\n"
                                "        worker = OperationRunWorker()\n"
                                "        worker.host = 'unreal'\n"
                                "        worker.operation_key = 'blueprint.scan'\n"
                                "        worker.args_json = '{\"asset_path\": \"/Game/Test/BP_Test\"}'\n"
                                "        worker_results = []\n"
                                "        worker.finished.connect(lambda ok, payload: worker_results.append((ok, payload)))\n"
                                "        worker.run()\n"
                                "        self.assertTrue(worker_results[-1][0])\n"
                                "        self.assertEqual(worker_results[-1][1]['result']['status'], 'backend_called')\n"
                                "        bad_worker = OperationRunWorker()\n"
                                "        bad_worker.host = 'unreal'\n"
                                "        bad_worker.operation_key = 'blueprint.scan'\n"
                                "        bad_worker.args_json = '{bad json}'\n"
                                "        bad_results = []\n"
                                "        bad_worker.finished.connect(lambda ok, payload: bad_results.append((ok, payload)))\n"
                                "        bad_worker.run()\n"
                                "        self.assertFalse(bad_results[-1][0])\n"
                                "        self.assertEqual(bad_results[-1][1]['error'], 'invalid_json')\n"
                                "\n"
                                "    def test_panel_refresh_template_run_and_result_output(self):\n"
                                "        panel = OperationRunnerPanel()\n"
                                "        self.assertGreaterEqual(len(panel._visible_rows), 1)\n"
                                "        panel.search_edit.setText('blueprint')\n"
                                "        self.assertEqual(panel.apply_filters(), 1)\n"
                                "        template = panel.populate_args_template()\n"
                                "        self.assertIn('asset_path', template)\n"
                                "        panel.args_editor.setPlainText('{\"asset_path\": \"/Game/Test/BP_Test\"}')\n"
                                "        panel.run_selected_operation()\n"
                                "        panel.worker.wait(5000)\n"
                                "        QApplication.processEvents()\n"
                                "        self.assertTrue(panel.run_button.isEnabled())\n"
                                "        self.assertIn('backend_called', panel.result_editor.toPlainText())\n"
                                "        panel.search_edit.setText('')\n"
                                "        panel.host_filter.setCurrentText('blender')\n"
                                "        self.assertEqual(panel.apply_filters(), 1)\n"
                                "        panel.operation_table.selectRow(0)\n"
                                "        template = panel.populate_args_template()\n"
                                "        self.assertIn('armature_name', template)\n"
                                "        panel.args_editor.setPlainText('{\"armature_name\": \"MannyRig\"}')\n"
                                "        panel.run_selected_operation()\n"
                                "        panel.worker.wait(5000)\n"
                                "        QApplication.processEvents()\n"
                                "        self.assertIn('dcc_backend_called', panel.result_editor.toPlainText())\n"
                            ),
                        },
                    ]
                    if wants_qt_operation_runner
                    else []
                ),
                "representative_code": expected_code_payload.get("representative_code", ""),
                "validation_commands": (
                    [
                        ["python", "-m", "py_compile", "tech_connector/ui/operation_runner_panel.py", "examples/tech_connector/tests/test_operation_runner_panel.py"],
                        ["python", "-m", "unittest", "examples.tech_connector.tests.test_operation_runner_panel"],
                    ]
                    if wants_qt_operation_runner
                    else []
                ),
                "copy_paths": [],
                "timeout_seconds": 30,
                "keep_workspace": True,
            },
            "dependencies": ["code.validate_expected_code passed", "disposable temp directory", "focused validation command list"],
            "expected_outputs": ["temp workspace path", "written generated files", "validation command exit codes", "no live tree mutation"],
        },
        "code.apply_patch": {
            "callable": "tech_connector.services.code_operation_service.apply_patch",
            "implementation_status": "registered_operation",
            "arguments": {
                "patch_source": "code.plan_patch output",
                "mechanism": "apply_patch",
                "safety": ["no unrelated refactor", "no staged-file mutation unless requested", "no destructive git commands"],
            },
            "dependencies": ["patch plan", "current file contents"],
            "expected_outputs": ["modified source files", "patch application result"],
        },
        "code.update_tests": {
            "callable": "tech_connector.services.code_operation_service.update_tests",
            "implementation_status": "registered_operation",
            "arguments": {
                "test_targets": "focused tests from code.inspect_symbols",
                "assertions": [
                    "operation reaches concrete callable",
                    "arguments/dependencies/validation are present",
                    "ambiguous prompt behavior is deterministic",
                ],
                "fixtures": "deterministic corpus fixture when prompt fuzzing is involved",
            },
            "dependencies": ["code.apply_patch", "test framework"],
            "expected_outputs": ["focused regression tests", "fixture updates if needed"],
        },
        "code.run_tests": {
            "callable": "tech_connector.services.code_operation_service.run_tests",
            "implementation_status": "registered_operation",
            "arguments": {
                "commands": ["python -m py_compile <changed python files>", "python -m unittest <focused tests>"],
                "timeout_policy": "focused first; broaden only when blast radius requires it",
                "report": ["commands", "exit codes", "failures", "remaining gaps"],
            },
            "dependencies": ["modified source files", "modified tests", "local Python runtime"],
            "expected_outputs": ["compile/test results", "failure summary", "remaining-risk report"],
        },
        "blueprint.scan": {
            "implementation_status": "registered_operation",
            "arguments": {
                "asset_paths": (
                    ["ABP_Locomotion", "ABP_Combat"]
                    if capability in {"abp_target_scan", "abp_crawl_integration"}
                    else (
                        ["BP_Rifle", "BP_Enemy"]
                        if capability == "niagara_target_scan"
                        else ["resolved facial AnimBP", "resolved MetaHuman asset"] if capability == "facial_animbp_slot_wiring" else ["resolved target asset"]
                    )
                ),
                "include_graphs": True,
                "include_variables": True,
                "include_components": True,
                "include_compile_status": True,
            },
            "dependencies": ["Unreal editor connection", "asset registry", "Blueprint graph readback support"],
            "expected_outputs": ["graph inventory", "variable/component list", "compile status", "target insertion points"],
        },
        "anim_graph.add_state": {
            "implementation_status": "registered_operation",
            "arguments": {
                "anim_blueprint": "resolved ABP_Locomotion or ABP_Combat asset path",
                "state_machine": "resolved locomotion/combat state machine",
                "state_name": "Crouch_Crawl",
                "pose_source": "resolved crawl animation or crawl BlendSpace",
                "metadata": {"feature": "rifle crouch-crawl", "preserve_existing_states": True},
            },
            "dependencies": ["blueprint.scan", "crawl animation/BlendSpace", "AnimGraph mutation wrapper"],
            "expected_outputs": ["new state asset graph node", "state readback record"],
        },
        "anim_graph.add_transition_rule": {
            "implementation_status": "registered_operation",
            "arguments": {
                "anim_blueprint": "resolved AnimBlueprint asset path",
                "state_machine": "resolved state machine",
                "transitions": [
                    {
                        "from": "Locomotion/IdleWalkRun or CombatLocomotion",
                        "to": "Crouch_Crawl",
                        "predicates": ["bIsCrouching", "bHasRifle", "speed <= crawl_max_speed", "not bIsJumping", "not bIsSprinting"],
                    },
                    {
                        "from": "Crouch_Crawl",
                        "to": "Locomotion/IdleWalkRun or CombatLocomotion",
                        "predicates": ["not bIsCrouching or bIsJumping or bIsSprinting"],
                    },
                ],
                "preserve_rules": ["sprint", "jump", "aim offset"],
            },
            "dependencies": ["anim_graph.add_state", "variable contract", "transition rule graph synthesis"],
            "expected_outputs": ["transition edges", "rule graphs", "predicate readback"],
        },
        "anim_graph.wire_state_machine_to_output_pose": {
            "implementation_status": "registered_operation",
            "arguments": {
                "anim_blueprint": "resolved AnimBlueprint asset path",
                "state_machine": "resolved state machine",
                "output_pose": "Final Animation Pose",
                "preserve_existing_pose_chain": True,
            },
            "dependencies": ["anim_graph.add_state", "anim_graph.add_transition_rule"],
            "expected_outputs": ["connected output pose pins", "graph readback proof"],
        },
        "blueprint.compile_and_save": {
            "implementation_status": "registered_operation",
            "arguments": {
                "asset_paths": ["resolved Blueprint/AnimBlueprint assets"],
                "save": True,
                "reload_after_save": True,
                "fail_on_compile_error": True,
            },
            "dependencies": ["all intended graph/asset mutations complete"],
            "expected_outputs": ["compile result", "save result", "reload/readback result"],
        },
        "niagara.create_emitter": {
            "implementation_status": "registered_operation",
            "arguments": {
                "emitters": [
                    {
                        "name": "NS_MuzzleFlash or NE_MuzzleFlash",
                        "package_path": "/Game/FX/Weapons",
                        "template": "resolved existing muzzle flash template or empty emitter",
                        "parameters": {"duration": "short burst", "socket": "Muzzle", "visibility": "cosmetic replicated event"},
                    },
                    {
                        "name": "NS_BulletImpact or NE_BulletImpact",
                        "package_path": "/Game/FX/Impacts",
                        "template": "resolved impact template or empty emitter",
                        "parameters": {"surface_response": "material/physical surface driven", "spawn_at": "hit result"},
                    },
                ]
            },
            "dependencies": ["Niagara plugin/API availability", "target content folder", "asset save/readback"],
            "expected_outputs": ["Niagara emitter/system assets", "readback class/property proof"],
        },
        "blueprint.attach_to_socket": {
            "callable": "unreal_tools.blueprint.attach_to_socket",
            "implementation_status": "registered_operation",
            "arguments": {
                "blueprint_path": "BP_Rifle or resolved weapon Blueprint",
                "component_name": "AIStudio_MuzzleFlashFX",
                "component_class": "/Script/Niagara.NiagaraComponent",
                "asset_path": "resolved Niagara muzzle effect",
                "socket_name": "Muzzle or resolved weapon muzzle socket",
                "attach_parent": "resolved skeletal mesh/component if available",
                "save": True,
            },
            "dependencies": ["blueprint.scan", "niagara.create_emitter", "socket readback"],
            "expected_outputs": ["socket attachment/spawn graph", "resolved socket proof"],
        },
        "blueprint.add_event": {
            "callable": "unreal_tools.blueprint.add_event",
            "implementation_status": "registered_operation",
            "arguments": {
                "blueprint": "resolved target Blueprint or AnimBlueprint",
                "events_or_functions": (
                    ["Expose/confirm bIsCrouching", "Expose/confirm bHasRifle", "Expose/confirm GroundSpeed", "Expose/confirm bIsJumping/bIsSprinting"]
                    if capability == "crawl_variable_contract"
                    else ["FireWeapon", "SpawnMuzzleFlash", "OnBulletImpact", "GameplayCue/replication boundary"]
                ),
                "graph": "AnimBlueprint EventGraph / variable update graph" if capability == "crawl_variable_contract" else "EventGraph or resolved function graph",
                "pin_contract": (
                    "animation update exec, movement component reads, weapon state read, boolean/float variable writes"
                    if capability == "crawl_variable_contract"
                    else "exec, target component, hit result, instigator, cosmetic authority guard"
                ),
            },
            "dependencies": ["blueprint.scan", "domain variable/event contract"],
            "expected_outputs": ["event/function nodes", "pin wiring", "compile-safe graph"],
        },
        "unreal.create_validation_map": {
            "callable": "unreal_tools.level.create_validation_map",
            "implementation_status": "registered_operation",
            "arguments": {
                "map_path": "/Game/Developers/AI_Validation/Disposable_TestMap",
                "spawn_actors": ["resolved character/weapon/enemy test actors"],
                "test_steps": ["trigger feature", "capture readback/log/proof", "restore or keep disposable map only"],
            },
            "dependencies": ["compiled assets", "safe disposable content path"],
            "expected_outputs": ["validation map", "spawn/test report", "rollback note"],
        },
        "blender.scan_animation": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "host": "blender",
                "operation_key": "blender.scan_animation",
                "scene": "active Blender scene or supplied .blend",
                "include_actions": True,
                "include_selected": True,
            },
            "dependencies": ["Blender connection", "active scene/readback"],
            "expected_outputs": ["armature/action inventory", "selected objects", "frame range", "scene scale"],
        },
        "blender.clean_animation": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "scene": "active Blender scene or supplied .blend",
                "armature": "resolved source armature",
                "action": "resolved crawl/mocap action",
                "cleanup": ["trim frame range", "remove jitter", "normalize root motion", "set scale/axes for Unreal"],
            },
            "dependencies": ["Blender connection", "source action readback"],
            "expected_outputs": ["cleaned action", "frame/root-motion report"],
        },
        "blender.export_fbx": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "output_path": "job_workspace/exports/crawl_cleaned.fbx",
                "selection": "resolved armature/action",
                "settings": {"axis_forward": "-Y", "axis_up": "Z", "apply_unit_scale": True, "bake_animation": True},
            },
            "dependencies": ["blender.clean_animation"],
            "expected_outputs": ["FBX file", "export settings manifest"],
        },
        "import_unreal_asset": {
            "implementation_status": "registered_operation",
            "arguments": {
                "source_file": "resolved FBX/animation/DNA-derived file",
                "destination_path": "/Game/Imported/AI_Staging",
                "target_skeleton": "resolved Manny/MetaHuman skeleton",
                "import_options": {"animation": True, "skeletal_mesh": False, "import_materials": False},
            },
            "dependencies": ["source file exists", "target Unreal skeleton/project path"],
            "expected_outputs": ["imported Unreal asset path", "import log", "asset load proof"],
        },
        "unreal.retarget_animation": {
            "callable": "unreal_tools.animation.retarget_animation",
            "implementation_status": "registered_operation",
            "arguments": {
                "source_animation": "imported animation asset",
                "source_skeletal_mesh_path": "resolved source skeletal mesh",
                "target_skeletal_mesh_path": "Manny target skeletal mesh",
                "output_path": "/Game/Animations/Retargeted",
                "retargeter_path": "resolved IK Retargeter if already known",
                "destination_suffix": "_Retargeted",
                "save": True,
            },
            "dependencies": ["import_unreal_asset", "IK rig/retargeter availability"],
            "expected_outputs": ["Manny-compatible animation asset", "retarget report"],
        },
        "unreal.create_blendspace": {
            "callable": "unreal_tools.animation.create_blendspace",
            "implementation_status": "registered_operation",
            "arguments": {
                "asset_path": "/Game/Animations/Locomotion/BS_Crawl",
                "skeleton_path": "Manny skeleton",
                "samples": [{"animation": "retargeted crawl animation", "axis": {"speed": "crawl speed", "direction": 0}}],
                "axis_x": {"name": "Speed", "min": 0.0, "max": "crawl_max_speed", "grid_num": 4},
                "axis_y": {"name": "Direction", "min": -180.0, "max": 180.0, "grid_num": 4},
                "save": True,
            },
            "dependencies": ["unreal.retarget_animation"],
            "expected_outputs": ["BlendSpace asset", "sample readback"],
        },
        "maya.adjust_facial_control_rig": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "scene": "active Maya scene or supplied file",
                "control_set": "resolved MetaHuman facial controls",
                "expression": "requested facial expression",
                "animation_range": "resolved or user-provided frame range",
                "export_path": "job_workspace/exports/metahuman_expression.fbx",
            },
            "dependencies": ["Maya connection", "facial controls readback"],
            "expected_outputs": ["keyed facial animation", "exported animation file"],
        },
        "maya.scan_facial_rig": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "host": "maya",
                "operation_key": "maya.scan_facial_rig",
                "scene": "active Maya scene or supplied file",
                "control_patterns": ["*_ctrl", "*CTRL*", "*face*", "*jaw*", "*brow*", "*eye*", "*mouth*"],
                "include_selection": True,
            },
            "dependencies": ["Maya connection", "active scene/readback"],
            "expected_outputs": ["facial control candidates", "selection", "timeline range", "export readiness"],
        },
        "metahuman.propagate_dna": {
            "callable": "tech_connector.services.unreal.metahuman_dna_operation_service.propagate_dna",
            "implementation_status": "registered_operation",
            "arguments": {
                "metahuman_dna_path": "resolved DNA file",
                "animation_or_scene_delta": "Maya facial adjustment output",
                "tool_root": "C:/depot/tools/external_tools/MetaHumanDNA if available",
                "output_path": "job_workspace/exports/metahuman_dna_update",
                "skip_if_unavailable": True,
            },
            "dependencies": ["MetaHumanDNA availability", "DNA source path", "Maya adjustment output"],
            "expected_outputs": ["DNA output/provenance or explicit unavailable reason"],
        },
        "unreal.hook_facial_animbp_slot": {
            "callable": "unreal_tools.blueprint.hook_facial_animbp_slot",
            "implementation_status": "registered_operation",
            "arguments": {
                "facial_anim_blueprint": "resolved facial AnimBP",
                "slot_name": "resolved facial slot",
                "animation_asset": "imported facial animation asset",
                "compile_after_wiring": True,
            },
            "dependencies": ["blueprint.scan", "import_unreal_asset"],
            "expected_outputs": ["slot wiring readback", "compile result"],
        },
        "sequencer.validate_playback": {
            "callable": "unreal_tools.sequencer.validate_playback",
            "implementation_status": "registered_operation",
            "arguments": {
                "sequence_path": "/Game/Developers/AI_Validation/Seq_FacialPlayback_Proof",
                "actor": "resolved MetaHuman actor or spawned validation actor",
                "animation_asset": "imported/hooked facial animation",
                "capture": ["playback status", "frame range", "warnings"],
            },
            "dependencies": ["unreal.hook_facial_animbp_slot", "validation level/actor"],
            "expected_outputs": ["Sequencer playback report", "validation proof artifact"],
        },
    }
    generic_plans = {
        "execute_internal_function": {
            "callable": "operation_catalog.resolve_and_execute",
            "implementation_status": "registry_lookup_required",
            "arguments": {
                "query": capability or str(item.get("label") or ""),
                "host": host,
                "required_capability": capability,
                "inputs": "resolved from operation contract artifacts",
            },
            "dependencies": ["authoritative operation catalog", "resolved callable metadata"],
            "expected_outputs": ["execution result", "called function id"],
        },
        "run_dcc_operation": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registry_lookup_required",
            "arguments": {
                "host": host,
                "operation_key": capability or "resolved host operation",
                "target": "resolved active asset/scene/node",
                "inputs": "resolved from host context and prompt slots",
            },
            "dependencies": ["host status green or plan-only fallback", "operation registry entry", "target resolver"],
            "expected_outputs": ["host operation result", "host readback"],
        },
        "run_python_function": {
            "callable": "local_python.execute_validated_helper",
            "implementation_status": "generated_or_registry_lookup_required",
            "arguments": {
                "function": "resolved indexed helper or generated wrapper",
                "inputs": "typed artifacts from previous step",
                "timeout_seconds": 60,
            },
            "dependencies": ["py_compile", "function signature contract"],
            "expected_outputs": ["return value", "files/artifacts produced"],
        },
        "validate_result": {
            "callable": "validation_planner.run_readback_checks",
            "implementation_status": "registered_operation",
            "arguments": {
                "capability": capability,
                "checks": list(item.get("validates_with") or []),
                "artifacts": "outputs from previous operation",
            },
            "dependencies": ["previous operation output"],
            "expected_outputs": ["validation report", "warnings/errors"],
        },
    }
    payload = dict(common)
    payload.update(plans.get(action_type) or generic_plans.get(action_type) or {})
    return payload


def _mixed_operation_sequence(adaptive_sequence: list[dict[str, Any]], decision: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    decision = dict(decision or {})
    steps: list[dict[str, Any]] = []
    index = 1
    for item in adaptive_sequence:
        for action_key in _action_keys_for_sequence_item(item, decision):
            action_type = _action_type_by_key(action_key)
            row = {
                "step": index,
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "action_type": action_type.key,
                "label": action_type.label,
                "category": action_type.category,
                "host": action_type.host,
                "requires_network": action_type.requires_network,
                "requires_approval": action_type.requires_approval,
                "requires_license_check": action_type.requires_license_check,
                "report_sources": action_type.report_sources,
                "validates_with": list(action_type.validates_with),
            }
            row["planned_call"] = _planned_call_for_action(row, decision)
            steps.append(row)
            index += 1
    return steps


def _artifact_type_by_key(key: str) -> ArtifactType:
    for artifact_type in ARTIFACT_TYPES:
        if artifact_type.key == key:
            return artifact_type
    return ARTIFACT_TYPES[0]


def _artifact_catalog() -> list[dict[str, Any]]:
    return [artifact_type.to_dict() for artifact_type in ARTIFACT_TYPES]


def _artifacts_for_action(action_type: str, capability: str, *, output: bool) -> list[dict[str, Any]]:
    mapping = {
        "execute_internal_function": (("executable_function",), ("execution_result",)),
        "run_python_function": (("source_code", "file"), ("execution_result", "compatibility_report")),
        "run_dcc_operation": (("blender_object", "maya_node", "unreal_asset"), ("execution_result", "skeleton", "skeletal_mesh")),
        "web_knowledge_search": (("documentation",), ("documentation", "asset_candidate_list")),
        "github_candidate_review": (("documentation",), ("repository", "license_record", "provenance_record")),
        "plugin_candidate_review": (("documentation",), ("plugin", "license_record", "provenance_record")),
        "download_or_ingest_asset": (("asset_candidate_list", "license_record"), ("file", "animation_clip", "provenance_record")),
        "import_unreal_asset": (("file", "animation_clip", "skeleton"), ("unreal_asset", "execution_result")),
        "blueprint.scan": (("unreal_asset",), ("workflow", "execution_result")),
        "anim_graph.add_state": (("unreal_asset", "animation_clip"), ("unreal_asset", "execution_result")),
        "anim_graph.add_transition_rule": (("unreal_asset", "workflow"), ("unreal_asset", "execution_result")),
        "anim_graph.wire_state_machine_to_output_pose": (("unreal_asset", "workflow"), ("unreal_asset", "execution_result")),
        "blueprint.compile_and_save": (("unreal_asset",), ("unreal_asset", "validation_report")),
        "niagara.create_emitter": (("unreal_asset", "source_code"), ("unreal_asset", "execution_result")),
        "blueprint.add_event": (("unreal_asset", "workflow"), ("unreal_asset", "execution_result")),
        "blueprint.attach_to_socket": (("unreal_asset", "workflow"), ("unreal_asset", "execution_result")),
        "unreal.create_validation_map": (("unreal_asset", "workflow"), ("validation_report", "unreal_asset")),
        "blender.clean_animation": (("blender_object", "animation_clip"), ("animation_clip", "execution_result")),
        "blender.export_fbx": (("animation_clip", "blender_object"), ("file", "provenance_record")),
        "unreal.retarget_animation": (("unreal_asset", "skeleton"), ("unreal_asset", "compatibility_report")),
        "unreal.create_blendspace": (("unreal_asset", "animation_clip", "skeleton"), ("unreal_asset", "execution_result")),
        "maya.adjust_facial_control_rig": (("maya_node",), ("animation_clip", "file", "execution_result")),
        "metahuman.propagate_dna": (("file", "animation_clip"), ("file", "provenance_record", "compatibility_report")),
        "unreal.hook_facial_animbp_slot": (("unreal_asset", "animation_clip"), ("unreal_asset", "execution_result")),
        "sequencer.validate_playback": (("unreal_asset", "animation_clip"), ("validation_report",)),
        "generate_code_or_wrapper": (("documentation", "compatibility_report"), ("source_code", "executable_function")),
        "register_capability": (("execution_result", "validation_report"), ("workflow", "executable_function")),
        "validate_result": (("execution_result",), ("validation_report",)),
    }
    inputs, outputs = mapping.get(action_type, (("file",), ("execution_result",)))
    selected = outputs if output else inputs
    return [
        {
            "artifact_type": key,
            "label": _artifact_type_by_key(key).label,
            "capability": capability,
            "required": not output,
        }
        for key in selected
    ]


def _execution_context_for_action(item: dict[str, Any]) -> dict[str, Any]:
    action_type = str(item.get("action_type") or "")
    host = str(item.get("host") or "")
    capability = str(item.get("capability") or "").lower()
    if not host:
        if action_type == "import_unreal_asset" or "unreal" in capability:
            host = "unreal"
        elif "blender" in capability:
            host = "blender"
        elif "maya" in capability:
            host = "maya"
        elif action_type in {"run_python_function", "generate_code_or_wrapper"}:
            host = "local_python"
        elif item.get("requires_network"):
            host = "web_service"
        else:
            host = "local"
    return {
        "host": host,
        "workspace": "job_workspace",
        "project": "active_project",
        "active_asset": "",
    }


def _provider_id_for_action(item: dict[str, Any]) -> str:
    action_type = str(item.get("action_type") or "")
    host = _execution_context_for_action(item).get("host", "local")
    if action_type == "web_knowledge_search":
        return "source_policy.research"
    if action_type == "github_candidate_review":
        return "github_ingest_service"
    if action_type == "plugin_candidate_review":
        return "plugin_registry"
    if action_type == "import_unreal_asset":
        return "unreal_bridge"
    if action_type == "run_dcc_operation":
        return f"{host}_bridge"
    if action_type == "run_python_function":
        return "local_python"
    if action_type.startswith("code."):
        return "local_code_operation_catalog"
    if action_type.startswith(("blueprint.", "anim_graph.", "niagara.", "unreal.", "sequencer.")):
        return "unreal_operation_catalog"
    if action_type.startswith("blender."):
        return "blender_operation_catalog"
    if action_type.startswith("maya."):
        return "maya_operation_catalog"
    if action_type.startswith("metahuman."):
        return "external_tools.metahuman_dna"
    return "tech_connector"


def _operation_action_contracts(mixed_sequence: list[dict[str, Any]], decision: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    decision = dict(decision or {})
    contracts: list[dict[str, Any]] = []
    for item in mixed_sequence:
        action_type = str(item.get("action_type") or "")
        capability = str(item.get("capability") or "")
        requires_network = bool(item.get("requires_network", False))
        requires_approval = bool(item.get("requires_approval", False))
        requires_license = bool(item.get("requires_license_check", False))
        planned_call = dict(item.get("planned_call") or _planned_call_for_action(item, decision))
        contracts.append(
            {
                "id": f"action_{int(item.get('step') or 0):03d}_{action_type}",
                "action_type": action_type,
                "capability": capability,
                "planned_call": planned_call,
                "callable": planned_call.get("callable", action_type),
                "call_arguments": planned_call.get("arguments", {}),
                "call_dependencies": planned_call.get("dependencies", []),
                "inputs": _artifacts_for_action(action_type, capability, output=False),
                "outputs": _artifacts_for_action(action_type, capability, output=True),
                "preconditions": [
                    "required inputs are present",
                    "execution context is available",
                    "user approval is recorded" if requires_approval else "",
                    "network is available" if requires_network else "",
                    "license is acceptable" if requires_license else "",
                ],
                "postconditions": [
                    "declared outputs are produced or failure is reported",
                    "validation evidence is captured",
                    "provenance is recorded for external resources" if requires_network else "",
                ],
                "execution_context": _execution_context_for_action(item),
                "execution_host": _execution_context_for_action(item).get("host", ""),
                "provider_id": _provider_id_for_action(item),
                "permissions": [
                    "network" if requires_network else "",
                    "user_approval" if requires_approval else "",
                    "license_review" if requires_license else "",
                ],
                "approval_policy": "required_before_execution" if requires_approval else "not_required",
                "network_requirement": "required" if requires_network else "not_required",
                "estimated_cost": None,
                "estimated_duration": None,
                "confidence": 0.72 if requires_network else 0.84,
                "retry_policy": {
                    "max_attempts": 2,
                    "retry_on": ["transient_failure", "timeout"] if requires_network else ["transient_failure"],
                },
                "rollback_policy": {
                    "strategy": "remove_outputs_or_restore_previous_state",
                    "requires_snapshot": action_type in {"import_unreal_asset", "download_or_ingest_asset", "generate_code_or_wrapper", "code.apply_patch"},
                },
                "validation_steps": list(planned_call.get("readback_validation") or item.get("validates_with") or []),
                "provenance": {
                    "trust_state": "approved_external" if requires_approval else ("source_reported" if requires_network else "trusted_internal_candidate"),
                    "source_url_required": bool(item.get("report_sources", False)),
                    "license_required": requires_license,
                    "security_review_required": action_type in {"github_candidate_review", "plugin_candidate_review", "download_or_ingest_asset"},
                },
            }
        )
    for contract in contracts:
        contract["preconditions"] = [item for item in contract["preconditions"] if item]
        contract["postconditions"] = [item for item in contract["postconditions"] if item]
        contract["permissions"] = [item for item in contract["permissions"] if item]
    return contracts


def _mixed_operation_graph(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = []
    edges = []
    for index, contract in enumerate(contracts):
        nodes.append(
            {
                "id": contract["id"],
                "action_type": contract["action_type"],
                "capability": contract["capability"],
                "execution_host": contract["execution_host"],
                "provider_id": contract["provider_id"],
                "planned_call": contract.get("planned_call", {}),
                "inputs": contract["inputs"],
                "outputs": contract["outputs"],
            }
        )
        if index > 0:
            previous = contracts[index - 1]
            edges.append(
                {
                    "from": previous["id"],
                    "to": contract["id"],
                    "artifact_flow": [
                        artifact.get("artifact_type", "")
                        for artifact in previous.get("outputs", [])
                        if artifact.get("artifact_type")
                    ][:3],
                    "condition": "previous action validated or produced recoverable warning",
                }
            )
    return {
        "framework": "mixed_operation_graph_v1",
        "base_graph": "tech_connector.services.action_graph_service.ActionGraph",
        "supports": [
            "typed_artifact_edges",
            "conditionals",
            "fallback_providers",
            "parallel_discovery",
            "approval_gates",
            "retries",
            "rollback",
            "human_interaction",
            "async_waits",
        ],
        "nodes": nodes,
        "edges": edges,
    }


def _action_graph_type_for_contract(contract: dict[str, Any]) -> str:
    action_type = str(contract.get("action_type") or "")
    mapping = {
        "execute_internal_function": "execute_dcc_capability",
        "run_python_function": "execute_python",
        "run_dcc_operation": "execute_dcc",
        "web_knowledge_search": "search_docs",
        "github_candidate_review": "github_search",
        "plugin_candidate_review": "resolve_dcc_capability",
        "download_or_ingest_asset": "github_ingest",
        "import_unreal_asset": "execute_unreal_python",
        "generate_code_or_wrapper": "generate_python",
        "register_capability": "index_repository",
        "validate_result": "validate",
    }
    if action_type.startswith(("blueprint.", "anim_graph.", "niagara.", "unreal.", "sequencer.")):
        return "execute_unreal_python"
    if action_type.startswith("code."):
        return "execute_python"
    if action_type.startswith("blender."):
        return "execute_dcc"
    if action_type.startswith("maya."):
        return "execute_dcc"
    if action_type.startswith("metahuman."):
        return "execute_python"
    return mapping.get(action_type, "validate")


def _canonical_action_graph(
    goal: str,
    contracts: list[dict[str, Any]],
    graph: dict[str, Any],
    materialization_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Represent mixed operations using the existing ActionGraph-compatible shape."""
    actions: list[dict[str, Any]] = []
    previous_id = ""
    for contract in contracts:
        action_id = contract.get("id", "")
        action_type = _action_graph_type_for_contract(contract)
        action = {
            "id": action_id,
            "action_id": action_id,
            "type": action_type,
            "action_type": action_type,
            "title": str(contract.get("action_type") or action_type).replace("_", " ").title(),
            "description": f"{contract.get('action_type', action_type)} for {contract.get('capability', '')}",
            "args": {
                "capability": contract.get("capability", ""),
                "provider_id": contract.get("provider_id", ""),
                "execution_context": contract.get("execution_context", {}),
                "planned_call": contract.get("planned_call", {}),
                "operation_contract": contract,
            },
            "input": {
                "capability": contract.get("capability", ""),
                "provider_id": contract.get("provider_id", ""),
                "execution_context": contract.get("execution_context", {}),
                "planned_call": contract.get("planned_call", {}),
                "operation_contract": contract,
            },
            "depends_on": [previous_id] if previous_id else [],
            "dependency_action_ids": [previous_id] if previous_id else [],
            "target_refs": contract.get("outputs", []),
            "source_refs": contract.get("inputs", []),
            "requires_approval": contract.get("approval_policy") == "required_before_execution",
            "status": "planned",
            "validation_status": "not_validated",
            "diagnostics": [
                "Generated from goal gap planner universal operation contract.",
                "Typed artifacts and execution context are carried in args.operation_contract.",
            ],
            "pipeline_materialization": (materialization_plan or {}).get("by_action_id", {}).get(action_id, {}),
        }
        actions.append(action)
        previous_id = action_id
    try:
        from tech_connector.services.action_graph_service import normalize_action_graph, validate_action_graph

        data = normalize_action_graph(
            {
                "goal": goal,
                "intent": "mixed_operation",
                "planner": "goal_gap_planning_service",
                "confidence": 0.72,
                "diagnostics": [
                    "Uses canonical ActionGraph with universal operation contracts attached.",
                    "mixed_operation_graph carries typed artifact edges and future graph features.",
                ],
                "actions": actions,
                "mixed_operation_graph": graph,
                "pipeline_materialization_plan": materialization_plan or {},
            }
        )
        data["validation"] = validate_action_graph(data)
        return data
    except Exception:
        return {
            "goal": goal,
            "intent": "mixed_operation",
            "planner": "goal_gap_planning_service",
            "confidence": 0.72,
            "diagnostics": ["ActionGraph normalization unavailable."],
            "actions": actions,
            "mixed_operation_graph": graph,
            "pipeline_materialization_plan": materialization_plan or {},
            "validation": {"valid": False, "errors": ["ActionGraph normalization unavailable."], "warnings": []},
        }


def _is_control_orchestration_action(action_type: str) -> bool:
    return action_type in {"github_candidate_review", "plugin_candidate_review"}


def _has_registered_callable(contract: dict[str, Any]) -> bool:
    action_type = str(contract.get("action_type") or "")
    provider = str(contract.get("provider_id") or "")
    if action_type == "execute_internal_function":
        return True
    if action_type == "run_dcc_operation" and provider.endswith("_bridge"):
        return True
    if action_type == "import_unreal_asset" and provider == "unreal_bridge":
        return True
    if action_type in {
        "code.search_project",
        "code.inspect_symbols",
        "code.plan_patch",
        "code.plan_expected_code",
        "code.validate_expected_code",
        "code.validate_patch_in_temp_workspace",
        "code.apply_patch",
        "code.update_tests",
        "code.run_tests",
        "blueprint.scan",
        "anim_graph.add_state",
        "anim_graph.add_transition_rule",
        "anim_graph.wire_state_machine_to_output_pose",
        "blueprint.compile_and_save",
        "blueprint.attach_to_socket",
        "blueprint.add_event",
        "niagara.create_emitter",
        "unreal.create_validation_map",
        "unreal.retarget_animation",
        "unreal.create_blendspace",
        "unreal.hook_facial_animbp_slot",
        "sequencer.validate_playback",
        "blender.scan_animation",
        "blender.clean_animation",
        "blender.export_fbx",
        "maya.scan_facial_rig",
        "maya.adjust_facial_control_rig",
        "metahuman.propagate_dna",
    }:
        return True
    if action_type in {"register_capability", "validate_result"}:
        return True
    return False


def _materialization_kind(contract: dict[str, Any]) -> str:
    action_type = str(contract.get("action_type") or "")
    if action_type in {"download_or_ingest_asset", "github_candidate_review", "plugin_candidate_review"}:
        return "third_party_wrapper"
    if action_type == "web_knowledge_search":
        return "provider_operation"
    if action_type in {"run_python_function", "generate_code_or_wrapper"}:
        return "generated_function"
    return "generated_adapter"


def _generated_capability_path(contract: dict[str, Any]) -> str:
    host = _function_slug(str(contract.get("execution_host") or "local"), fallback="local")
    capability = _function_slug(str(contract.get("capability") or contract.get("action_type") or "operation"))
    action_type = str(contract.get("action_type") or "")
    if action_type in {"download_or_ingest_asset", "github_candidate_review", "plugin_candidate_review"}:
        return f"third_party/wrappers/{capability}/adapter.py"
    if action_type == "web_knowledge_search":
        return f"tool_output/generated_adapters/{host}/{capability}_provider.py"
    return f"tool_output/generated_functions/{host}/{capability}.py"


def _manifest_path_for_implementation(implementation_path: str) -> str:
    base = implementation_path.rsplit(".", 1)[0]
    return f"{base}.manifest.yaml"


def _pipeline_materialization_plan(
    contracts: list[dict[str, Any]],
    graph: dict[str, Any],
    canonical_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan how a solved mixed operation can become a reusable pipeline.

    Planning may mention generated files, but it must not write them. Actual
    function generation belongs to an approved materialization/save step.
    """
    candidates: list[dict[str, Any]] = []
    by_action_id: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        action_id = str(contract.get("id") or "")
        action_type = str(contract.get("action_type") or "")
        capability = str(contract.get("capability") or action_type)
        control_node = _is_control_orchestration_action(action_type)
        registered = _has_registered_callable(contract)
        materializable = not control_node
        implementation_path = ""
        manifest_path = ""
        entry_point = ""
        status = "registered_callable" if registered else "planned_not_written"
        if materializable and not registered:
            implementation_path = _generated_capability_path(contract)
            manifest_path = _manifest_path_for_implementation(implementation_path)
            entry_point = "execute"
        node_plan = {
            "action_id": action_id,
            "capability": capability,
            "action_type": action_type,
            "node_kind": "control_flow" if control_node else "executable_operation",
            "pipeline_node_type": "approval_or_selection" if control_node else "operation",
            "registered_callable": registered,
            "materializable": materializable,
            "materialization_kind": "control_node" if control_node else (_materialization_kind(contract) if not registered else "existing_callable"),
            "status": "control_node_no_function_required" if control_node else status,
            "promotion_scope_default": "pipeline_local" if not registered else "internal",
            "trust_state": (
                "orchestration_only"
                if control_node
                else ("trusted_internal" if registered else "untrusted_until_validated")
            ),
            "implementation": {
                "path": implementation_path,
                "entry_point": entry_point,
                "contract": "OperationContext + inputs -> OperationResult",
            },
            "manifest": {
                "path": manifest_path,
                "schema": "tech_connector.operation_manifest.v1" if manifest_path else "",
                "must_declare": [
                    "id",
                    "entry_point",
                    "inputs",
                    "outputs",
                    "host_environment",
                    "dependencies",
                    "provenance",
                    "trust_level",
                    "validation_state",
                    "pipeline_node_metadata",
                ] if manifest_path else [],
            },
            "inputs": list(contract.get("inputs") or []),
            "outputs": list(contract.get("outputs") or []),
            "validation": {
                "required": bool(materializable),
                "steps": list(contract.get("validation_steps") or []),
                "minimum_checks": [
                    "generated implementation imports or host adapter resolves",
                    "declared inputs and outputs match operation contract",
                    "manifest validates",
                    "operation can be called by pipeline runtime",
                ] if materializable and not registered else [],
            },
            "registration": {
                "required_before_pipeline_run": bool(materializable and not registered),
                "registry_target": "capability_registry",
                "replace_temporary_action_with": f"capability:{_function_slug(capability)}" if materializable and not registered else "",
            },
        }
        by_action_id[action_id] = node_plan
        if contract.get("approval_policy") == "required_before_execution":
            candidates.append(
                {
                    "action_id": f"{action_id}_approval",
                    "capability": capability,
                    "action_type": "approval_gate",
                    "node_kind": "control_flow",
                    "pipeline_node_type": "approval_or_selection",
                    "registered_callable": False,
                    "materializable": False,
                    "materialization_kind": "control_node",
                    "status": "control_node_no_function_required",
                    "promotion_scope_default": "pipeline_local",
                    "trust_state": "orchestration_only",
                    "implementation": {
                        "path": "",
                        "entry_point": "",
                        "contract": "approval decision -> continuation state",
                    },
                    "manifest": {
                        "path": "",
                        "schema": "",
                        "must_declare": [],
                    },
                    "inputs": [
                        {
                            "artifact_type": "provenance_record",
                            "label": "ProvenanceRecord",
                            "capability": capability,
                            "required": True,
                        }
                    ],
                    "outputs": [
                        {
                            "artifact_type": "execution_result",
                            "label": "ExecutionResult",
                            "capability": capability,
                            "required": False,
                        }
                    ],
                    "validation": {
                        "required": True,
                        "steps": ["approval is recorded", "selected candidate or operation parameters are explicit"],
                        "minimum_checks": [],
                    },
                    "registration": {
                        "required_before_pipeline_run": False,
                        "registry_target": "pipeline_control_nodes",
                        "replace_temporary_action_with": "",
                    },
                }
            )
        candidates.append(node_plan)

    generated = [item for item in candidates if item["materializable"] and not item["registered_callable"]]
    return {
        "framework": "mixed_operation_materializer_v1",
        "base_graph": graph.get("base_graph", "tech_connector.services.action_graph_service.ActionGraph"),
        "convertible": True,
        "status": "planned_not_written",
        "generated_function_root": "tool_output/generated_functions",
        "generated_adapter_root": "tool_output/generated_adapters",
        "third_party_wrapper_root": "third_party/wrappers",
        "pipeline_package_root": "pipelines/<pipeline_id>",
        "default_promotion_scope": "pipeline_local",
        "promotion_scopes": [
            "temporary_job",
            "pipeline_local",
            "project",
            "user_library",
            "trusted_global",
        ],
        "promotion_policy": [
            "Do not promote generated or third-party code to global trust automatically.",
            "Pipeline-local is the safest default for newly generated functions.",
            "Externally sourced code must be wrapped and must keep license/provenance records.",
            "Credentials must be stored as references, not embedded in generated functions or manifests.",
        ],
        "materialization_steps": [
            "Inspect completed mixed-operation graph.",
            "Reuse registered callables where contracts already match.",
            "Generate functions, adapters, or wrappers only for materializable executable steps without callables.",
            "Write manifests and tests beside generated implementations.",
            "Validate each callable independently.",
            "Register validated capabilities.",
            "Replace temporary action IDs with stable operation IDs.",
            "Emit a pipeline-ready ActionGraph/workflow package.",
        ],
        "pipeline_node_candidates": candidates,
        "generated_callable_candidates": generated,
        "by_action_id": by_action_id,
        "reproducibility_checks": [
            "Every executable step has a callable implementation or generated wrapper plan.",
            "All dependencies, host versions, credentials, approvals, and provenance are explicit.",
            "User choices are represented as pipeline inputs or approval nodes.",
            "External assets are dynamically resolved or safely referenced with license records.",
            "Rollback and validation steps survive conversion from mixed operation to pipeline.",
        ],
        "canonical_action_graph": {
            "framework": "tech_connector.services.action_graph_service.ActionGraph",
            "action_count": len((canonical_graph or {}).get("actions") or []),
            "validation": (canonical_graph or {}).get("validation", {}),
        },
    }


def _approval_gates(strategy_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    for item in strategy_plan:
        for strategy in list(item.get("strategies") or []):
            if not isinstance(strategy, dict):
                continue
            if not strategy.get("pause_before_execution"):
                continue
            gates.append(
                {
                    "capability": item.get("capability", ""),
                    "label": item.get("label", ""),
                    "strategy": strategy.get("key", ""),
                    "requires_link": True,
                    "requires_fit_explanation": True,
                    "requires_license_check": bool(strategy.get("requires_license_check", False)),
                    "requires_user_approval": True,
                    "approval_prompt": strategy.get("approval_prompt", ""),
                }
            )
    return gates


def _source_report_requirements(strategy_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for item in strategy_plan:
        for strategy in list(item.get("strategies") or []):
            if not isinstance(strategy, dict):
                continue
            if not strategy.get("requires_internet") or strategy.get("pause_before_execution"):
                continue
            requirements.append(
                {
                    "capability": item.get("capability", ""),
                    "label": item.get("label", ""),
                    "strategy": strategy.get("key", ""),
                    "report_links": True,
                    "report_relevance": True,
                    "report_knowledge_added": True,
                    "approval_required": False,
                    "report_prompt": strategy.get("approval_prompt", ""),
                }
            )
    return requirements


def _planned_actions_from_path(path: list[dict[str, Any]], options: list[GapResolutionOption]) -> list[str]:
    actions: list[str] = []
    if path:
        actions.append("Inspect and confirm the current goal, target context, and existing capabilities before editing.")
    for item in path[1:7]:
        label = str(item.get("label") or item.get("capability") or "").strip()
        status = str(item.get("status") or "").strip()
        if not label:
            continue
        if status == "known":
            actions.append(f"Reuse or extend: {label}.")
        elif status == "missing_or_unverified":
            actions.append(f"Resolve missing prerequisite: {label}.")
        else:
            actions.append(f"Discover and verify: {label}.")
    if options:
        actions.append(f"Prefer the highest-confidence resolution option: {options[0].label}.")
    actions.append("Stop for approval before risky, destructive, ambiguous, or broad mutation.")
    actions.append("Report progress at each long-running stage and hand off compact findings to the next stage.")
    return list(_uniq(actions))


def _needs_detailed_progress(
    decision: dict[str, Any],
    missing_links: list[dict[str, Any]],
    path: list[dict[str, Any]],
    patterns: list[CapabilityPattern],
) -> bool:
    if len(patterns) == 1 and patterns[0].key.startswith("quick."):
        return False
    if missing_links:
        return True
    if len(path) > 4:
        return True
    if decision.get("requires_plan") or decision.get("requires_confirmation") or decision.get("requires_dcc_connection"):
        return True
    if str(decision.get("risk_level") or "").lower() in {"medium", "high"}:
        return True
    if str(decision.get("compound_kind") or "atomic") != "atomic":
        return True
    mutation = str(decision.get("mutation_scope") or "")
    return bool(mutation and mutation != "read_only")


def _test_plan_from_path(path: list[dict[str, Any]], options: list[GapResolutionOption]) -> list[str]:
    tests: list[str] = []
    for item in path:
        for check in list(item.get("verify") or [])[:2]:
            tests.append(str(check))
    if options:
        tests.append(f"Validate that the selected resolution option worked: {options[0].label}.")
    tests.extend(
        [
            "Confirm the original user-facing goal works in the target app or project.",
            "Confirm existing related behavior still works and was not duplicated or broken.",
            "Report anything that could not be verified and the next safest validation step.",
        ]
    )
    return list(_uniq(tests))[:12]


def _report_outline(needs_detailed_progress: bool) -> list[str]:
    if not needs_detailed_progress:
        return [
            "Completed action",
            "Result or blocker",
        ]
    return [
        "Goal and context used",
        "Path selected and why",
        "Planned actions before mutation",
        "Targets/files/assets/graphs affected",
        "Edits made or operations performed",
        "What was reused versus created",
        "Validation and user test steps",
        "Warnings, unresolved assumptions, rollback or recovery notes",
        "Learning recommendations for future capability gaps",
        "Final outcome: completed, partially completed, blocked, failed, or rolled back",
    ]


def build_goal_gap_plan(prompt: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        custom_module = settings.get("planning_provider_module")
        if custom_module and custom_module != "default":
            from tech_connector.services.modular_provider_utils import invoke_custom_provider
            return invoke_custom_provider(
                f"{custom_module}.build_goal_gap_plan",
                _build_goal_gap_plan_impl,
                prompt,
                decision
            )
    except Exception as e:
        print(f"Error calling custom build_goal_gap_plan: {e}", flush=True)
    return _build_goal_gap_plan_impl(prompt, decision)

def _build_goal_gap_plan_impl(prompt: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build an A-to-Z plan only after the problem is adequately formulated."""
    decision = dict(decision or {})
    decision.setdefault("prompt", prompt)
    decision.setdefault("original_prompt", prompt)
    problem_formulation = _build_problem_formulation(prompt, decision)
    decision["problem_formulation"] = problem_formulation

    # Capability matching may use the original wording, but the formulated
    # problem is authoritative for goal, prerequisites, success, and whether
    # execution is allowed to continue.
    quick_allowed = (
        bool(problem_formulation.get("adequate"))
        and not _problem_formulation_requires_pause(problem_formulation)
        and _is_quick_direct_action(decision)
    )
    patterns = [_quick_direct_pattern(prompt, decision)] if quick_allowed else _matched_patterns(prompt, decision)
    if not patterns:
        # A request is only "quick direct" after formulation confirms that it
        # is actually an execution/direct-action problem rather than a source
        # question containing executable words.
        patterns = [_generic_pattern(prompt, decision)]

    goal = str(
        problem_formulation.get("interpreted_problem")
        or problem_formulation.get("desired_outcome")
        or _goal_from_prompt(prompt)
    )
    known_evidence = _known_capability_evidence(decision, prompt)
    nodes: list[CapabilityNode] = [
        CapabilityNode(
            key="user_goal",
            label=goal,
            status="target",
            evidence=("current prompt", "problem formulation"),
            produces=tuple(problem_formulation.get("deliverables") or ["desired outcome"]),
            verification=tuple(problem_formulation.get("success_conditions") or ["user-visible outcome is testable"]),
        )
    ]
    formulation_nodes = _capability_nodes_from_problem_formulation(problem_formulation)
    pattern_nodes: list[CapabilityNode] = []
    options: list[GapResolutionOption] = []
    questions: list[str] = []
    learning: list[str] = []
    labels: list[str] = []

    for pattern in patterns:
        labels.extend(pattern.labels)
        pattern_nodes.extend(pattern.required_chain)
        options.extend(pattern.resolution_options)
        questions.extend(pattern.questions)
        learning.extend(pattern.learning_recommendations)
    has_specific_pattern = any(
        not pattern.key.startswith(("generic.", "quick."))
        for pattern in patterns
    )
    if has_specific_pattern:
        nodes.extend(pattern_nodes)
    else:
        nodes.extend(formulation_nodes)
        nodes.extend(pattern_nodes)

    deduped_nodes: list[CapabilityNode] = []
    seen_nodes: set[str] = set()
    for node in nodes:
        if node.key in seen_nodes:
            continue
        seen_nodes.add(node.key)
        status = node.status
        evidence = list(node.evidence)
        if node.key != "user_goal":
            label_terms = _terms(node.label)
            if known_evidence and any(term in " ".join(known_evidence).lower() for term in label_terms if len(term) > 4):
                status = "known"
                evidence.extend(known_evidence[:3])
            elif node.requires:
                status = "missing_or_unverified"
            else:
                status = "discoverable"
        deduped_nodes.append(
            CapabilityNode(
                key=node.key,
                label=node.label,
                status=status,
                evidence=_uniq(evidence),
                requires=node.requires,
                produces=node.produces,
                verification=node.verification,
            )
        )

    ranked_options = sorted(options, key=lambda item: item.confidence, reverse=True)
    missing_links = [
        {
            "from": deduped_nodes[index - 1].key if index > 0 else "start",
            "to": node.key,
            "label": node.label,
            "status": node.status,
            "requires": list(node.requires),
            "verification": list(node.verification),
        }
        for index, node in enumerate(deduped_nodes)
        if node.status in {"missing_or_unverified", "unknown", "discoverable"}
    ]
    recommended_path = [
        {
            "step": index,
            "capability": node.key,
            "label": node.label,
            "status": node.status,
            "verify": list(node.verification[:2]),
        }
        for index, node in enumerate(deduped_nodes, start=1)
    ]
    capability_resolution_plan = _resolution_strategy_plan(deduped_nodes, decision)
    adaptive_sequence = _adaptive_sequence(capability_resolution_plan)
    mixed_operation_sequence = _mixed_operation_sequence(adaptive_sequence, decision)
    operation_contracts = _operation_action_contracts(mixed_operation_sequence, decision)
    mixed_operation_graph = _mixed_operation_graph(operation_contracts)
    pipeline_materialization_plan = _pipeline_materialization_plan(operation_contracts, mixed_operation_graph)
    canonical_action_graph = _canonical_action_graph(
        goal,
        operation_contracts,
        mixed_operation_graph,
        pipeline_materialization_plan,
    )
    pipeline_materialization_plan["canonical_action_graph"] = {
        "framework": "tech_connector.services.action_graph_service.ActionGraph",
        "intent": canonical_action_graph.get("intent", ""),
        "planner": canonical_action_graph.get("planner", ""),
        "action_count": len(canonical_action_graph.get("actions") or []),
        "validation": canonical_action_graph.get("validation", {}),
    }
    canonical_action_graph["pipeline_materialization_plan"] = pipeline_materialization_plan
    approval_gates = _approval_gates(capability_resolution_plan)
    source_report_requirements = _source_report_requirements(capability_resolution_plan)
    needs_detailed_progress = _needs_detailed_progress(decision, missing_links, recommended_path, patterns)
    planned_actions = _planned_actions_from_path(recommended_path, ranked_options) if needs_detailed_progress else []
    test_plan = _test_plan_from_path(recommended_path, ranked_options) if needs_detailed_progress else []

    return {
        "framework": "goal_gap_planning_v2",
        "goal": goal,
        "problem_formulation": problem_formulation,
        "meaning_graph": dict(problem_formulation.get("meaning_graph") or {}),
        "problem_adequate": bool(problem_formulation.get("adequate")),
        "problem_can_plan": bool(problem_formulation.get("can_plan")),
        "problem_requires_clarification": bool(problem_formulation.get("requires_clarification")),
        "matched_patterns": _uniq(pattern.key for pattern in patterns),
        "capability_labels": _uniq(labels),
        "known_evidence": list(known_evidence),
        "capability_nodes": [node.to_dict() for node in deduped_nodes],
        "missing_links": missing_links,
        "resolution_options": [option.to_dict() for option in ranked_options[:6]],
        "recommended_gap_path": recommended_path,
        "capability_resolution_plan": capability_resolution_plan,
        "adaptive_sequence": adaptive_sequence,
        "operation_action_catalog": _operation_action_catalog(),
        "artifact_type_catalog": _artifact_catalog(),
        "mixed_operation_sequence": mixed_operation_sequence,
        "operation_contracts": operation_contracts,
        "mixed_operation_graph": mixed_operation_graph,
        "canonical_action_graph": canonical_action_graph,
        "pipeline_materialization_plan": pipeline_materialization_plan,
        "approval_gates": approval_gates,
        "source_report_requirements": source_report_requirements,
        "progress_mode": "detailed" if needs_detailed_progress else "terse",
        "planned_actions": planned_actions,
        "test_plan": test_plan,
        "report_outline": _report_outline(needs_detailed_progress),
        "questions": _uniq(questions),
        "learning_recommendations": _uniq(learning),
        "planning_rules": [
            "Do not route, retrieve, mutate, or execute until the problem formulation is adequate.",
            "Generate the capability/task graph from the meaning graph and desired deliverables, not from raw token overlap.",
            "A handler result is not completion unless it satisfies the problem formulation success conditions.",
            "Treat every missing prerequisite as a planning node, not a failure.",
            "Ask what produces each missing capability before asking the user.",
            "Rank multiple resolution options before choosing one.",
            "For quick direct actions, keep the user report terse and completion-focused.",
            "For longer, risky, or uncertain work, use a documentation-level breakdown of goal, path, targets, edits, validation, risks, and outcome.",
            "Each capability node may resolve through internal functions, workflows, composition, local/project search, official docs, GitHub/plugin acquisition, generated code, or user approval.",
            "Mixed operation sequences may combine internal functions, Python helpers, DCC operations, asset acquisition, imports, validation, and capability registration.",
            "Use the existing ActionGraph as the canonical graph shape; attach universal operation contracts for typed artifacts, state transitions, context, retry, rollback, and provenance.",
            "Every successful mixed operation should be convertible into a pipeline; every executable step must have a registered callable or a generated/wrapped callable plan before pipeline save/run.",
            "Generated functions belong under tool_output/generated_functions or tool_output/generated_adapters by default; third-party code belongs behind wrappers under third_party/wrappers with license and provenance manifests.",
            "Ask for approval before materializing untrusted generated or external code, then validate and register it before making it a reusable pipeline node.",
            "New action types should be added to the action catalog instead of hardcoding new planner branches.",
            "If a capability is acquired or generated, validate it and register it before continuing the original plan.",
            "Web/official knowledge research may proceed without pausing, but the report must include links found, relevance, and what knowledge was used or added.",
            "Before GitHub/plugin/marketplace ingestion, pause and show links, relevance, license/approval needs, and the intended ingest/use plan.",
            "Use local/project knowledge first and request research only when local confidence is weak.",
            "Keep reporting visible progress during long context, model, tool, daemon, or validation work.",
            "After execution, recommend reusable capability relationships that should be persisted.",
        ],
        "next_action": (
            "clarify_problem"
            if _problem_formulation_requires_pause(problem_formulation)
            else ("resolve_missing_links" if missing_links else "execute_validated_path")
        ),
    }


def goal_gap_planning_context(prompt: str, decision: dict[str, Any] | None = None, *, max_chars: int = 3000) -> str:
    plan = build_goal_gap_plan(prompt, decision)
    formulation = dict(plan.get("problem_formulation") or {})
    lines = [
        "GOAL GAP PLANNING:",
        "Use this to connect the user's A-to-Z goal through required intermediate capabilities before execution.",
        f"Goal: {plan['goal']}",
        f"Problem adequate: {str(bool(plan.get('problem_adequate'))).lower()}",
        f"Can plan: {str(bool(plan.get('problem_can_plan'))).lower()}",
        f"Progress mode: {plan.get('progress_mode', 'detailed')}",
    ]
    if formulation:
        lines.extend([
            "Problem formulation:",
            f"- Literal request: {formulation.get('literal_request', '')}",
            f"- Interpreted problem: {formulation.get('interpreted_problem', '')}",
            f"- Desired outcome: {formulation.get('desired_outcome', '')}",
            f"- Deliverables: {', '.join(formulation.get('deliverables') or [])}",
            f"- Action mode: {formulation.get('action_mode', '')}",
        ])
        if formulation.get("unknowns"):
            lines.append("- Unknowns: " + " | ".join(list(formulation.get("unknowns") or [])[:5]))
        if formulation.get("exclusions"):
            lines.append("- Exclusions: " + " | ".join(list(formulation.get("exclusions") or [])[:4]))
    lines.append("Planning rules:")
    lines.extend(f"- {rule}" for rule in plan.get("planning_rules") or [])
    if plan.get("known_evidence"):
        lines.append("Known evidence:")
        lines.extend(f"- {item}" for item in plan["known_evidence"][:6])
    if plan.get("missing_links"):
        lines.append("Missing or unverified links:")
        for link in plan["missing_links"][:8]:
            req = "; ".join(link.get("requires") or [])
            suffix = f" requires {req}" if req else ""
            lines.append(f"- {link.get('label')} ({link.get('status')}){suffix}")
    if plan.get("resolution_options"):
        lines.append("Resolution options:")
        for option in plan["resolution_options"][:4]:
            lines.append(f"- {option['label']} confidence={option['confidence']:.2f}")
            for step in option.get("steps", [])[:4]:
                lines.append(f"  - {step}")
    if plan.get("capability_resolution_plan"):
        lines.append("Capability resolution strategy per step:")
        for item in plan["capability_resolution_plan"][:8]:
            strategies = item.get("strategies") or []
            chosen = item.get("chosen_strategy") or ""
            detail = ""
            if strategies:
                first = strategies[0]
                detail = (
                    f" confidence={float(first.get('confidence') or 0):.2f}"
                    f" internet={str(bool(first.get('requires_internet'))).lower()}"
                    f" approval={str(bool(first.get('requires_approval'))).lower()}"
                )
            lines.append(f"- {item.get('label')} -> {chosen}{detail}")
    if plan.get("adaptive_sequence"):
        lines.append("Adaptive execution sequence:")
        for item in plan["adaptive_sequence"][:8]:
            lines.append(f"- {item.get('action')}: {item.get('label')} via {item.get('strategy')}")
    if plan.get("mixed_operation_sequence"):
        lines.append("Mixed operation sequence:")
        for item in plan["mixed_operation_sequence"][:10]:
            flags = []
            if item.get("requires_network"):
                flags.append("network")
            if item.get("requires_approval"):
                flags.append("approval")
            if item.get("requires_license_check"):
                flags.append("license")
            flag_text = f" ({', '.join(flags)})" if flags else ""
            planned_call = dict(item.get("planned_call") or {})
            call_arguments = dict(planned_call.get("arguments") or {})
            arg_keys = ", ".join(list(call_arguments.keys())[:6])
            callable_name = planned_call.get("callable", "")
            call_text = f" call={callable_name}" if callable_name else ""
            args_text = f" args=[{arg_keys}]" if arg_keys else ""
            lines.append(f"- {item.get('action_type')}: {item.get('capability')} via {item.get('strategy')}{flag_text}{call_text}{args_text}")
    if plan.get("operation_contracts"):
        lines.append("Universal action contracts:")
        for contract in plan["operation_contracts"][:6]:
            inputs = ", ".join(item.get("artifact_type", "") for item in contract.get("inputs", [])[:3])
            outputs = ", ".join(item.get("artifact_type", "") for item in contract.get("outputs", [])[:3])
            call_arguments = dict(contract.get("call_arguments") or {})
            arg_keys = ", ".join(list(call_arguments.keys())[:6])
            call_text = f" call={contract.get('callable', '')}" if contract.get("callable") else ""
            args_text = f" args=[{arg_keys}]" if arg_keys else ""
            lines.append(
                f"- {contract.get('id')}: {contract.get('action_type')} on {contract.get('execution_host')} "
                f"inputs=[{inputs}] outputs=[{outputs}]{call_text}{args_text}"
            )
    if plan.get("mixed_operation_graph"):
        graph = plan["mixed_operation_graph"]
        lines.append(
            f"Canonical graph basis: {graph.get('base_graph', 'ActionGraph')} "
            f"nodes={len(graph.get('nodes') or [])} edges={len(graph.get('edges') or [])}"
        )
    if plan.get("pipeline_materialization_plan"):
        materializer = plan["pipeline_materialization_plan"]
        lines.append("Pipeline materialization:")
        lines.append(
            f"- Convertible={str(bool(materializer.get('convertible'))).lower()} "
            f"default_scope={materializer.get('default_promotion_scope', '')} "
            f"generated_candidates={len(materializer.get('generated_callable_candidates') or [])}"
        )
        for item in list(materializer.get("generated_callable_candidates") or [])[:5]:
            implementation = item.get("implementation") or {}
            lines.append(
                f"- {item.get('capability')}: {item.get('materialization_kind')} -> "
                f"{implementation.get('path', '')}"
            )
    if plan.get("approval_gates"):
        lines.append("Source review / approval gates:")
        for gate in plan["approval_gates"][:6]:
            lines.append(
                f"- Pause before {gate.get('strategy')} for {gate.get('label')}: "
                "show links, relevance, license/approval needs, and intended use."
            )
    if plan.get("source_report_requirements"):
        lines.append("Knowledge source reporting after research:")
        for item in plan["source_report_requirements"][:6]:
            lines.append(f"- {item.get('strategy')} for {item.get('label')}: report links found, relevance, and knowledge used/added.")
    if plan.get("planned_actions"):
        lines.append("Planned actions to explain before mutation:")
        lines.extend(f"- {item}" for item in plan["planned_actions"][:8])
    if plan.get("test_plan"):
        lines.append("How the user can test or verify this:")
        lines.extend(f"- {item}" for item in plan["test_plan"][:8])
    if plan.get("report_outline"):
        lines.append("Required response/report outline:")
        lines.extend(f"- {item}" for item in plan["report_outline"][:10])
    if plan.get("learning_recommendations"):
        lines.append("Learning recommendations after this workflow:")
        lines.extend(f"- {item}" for item in plan["learning_recommendations"][:5])
    text = "\n".join(lines)
    return text[:max_chars].rstrip()


def compact_goal_gap_plan(
    plan: dict[str, Any] | None,
    *,
    max_links: int = 5,
    max_options: int = 3,
    max_learning: int = 3,
    max_actions: int = 3,
    max_tests: int = 3,
) -> dict[str, Any]:
    """Return a route-metadata friendly gap plan."""
    plan = dict(plan or {})
    formulation = dict(plan.get("problem_formulation") or {})
    return {
        "framework": plan.get("framework", "goal_gap_planning_v2"),
        "goal": plan.get("goal", ""),
        "problem_formulation": {
            "interpreted_problem": formulation.get("interpreted_problem", ""),
            "desired_outcome": formulation.get("desired_outcome", ""),
            "deliverables": list(formulation.get("deliverables") or []),
            "action_mode": formulation.get("action_mode", ""),
            "unknowns": list(formulation.get("unknowns") or [])[:max_links],
            "blocking_unknowns": list(formulation.get("blocking_unknowns") or [])[:max_links],
            "exclusions": list(formulation.get("exclusions") or [])[:max_links],
            "success_conditions": list(formulation.get("success_conditions") or [])[:max_links],
            "candidate_plan": list(formulation.get("candidate_plan") or [])[:max_links * 2],
            "adequate": bool(formulation.get("adequate")),
            "can_plan": bool(formulation.get("can_plan")),
            "requires_clarification": bool(formulation.get("requires_clarification")),
            "confidence": float(formulation.get("confidence") or 0.0),
        },
        "matched_patterns": list(plan.get("matched_patterns") or [])[:6],
        "next_action": plan.get("next_action", ""),
        "progress_mode": plan.get("progress_mode", ""),
        "missing_links": [
            {
                "label": link.get("label", ""),
                "status": link.get("status", ""),
                "requires": list(link.get("requires") or [])[:3],
            }
            for link in list(plan.get("missing_links") or [])[:max_links]
            if isinstance(link, dict)
        ],
        "resolution_options": [
            {
                "key": option.get("key", ""),
                "label": option.get("label", ""),
                "confidence": option.get("confidence", 0),
                "requires_approval": bool(option.get("requires_approval", False)),
            }
            for option in list(plan.get("resolution_options") or [])[:max_options]
            if isinstance(option, dict)
        ],
        "capability_resolution_plan": [
            {
                "capability": item.get("capability", ""),
                "label": item.get("label", ""),
                "status": item.get("status", ""),
                "chosen_strategy": item.get("chosen_strategy", ""),
                "strategies": [
                    {
                        "key": strategy.get("key", ""),
                        "confidence": strategy.get("confidence", 0),
                        "requires_internet": bool(strategy.get("requires_internet", False)),
                        "requires_approval": bool(strategy.get("requires_approval", False)),
                        "requires_license_check": bool(strategy.get("requires_license_check", False)),
                    }
                    for strategy in list(item.get("strategies") or [])[:2]
                    if isinstance(strategy, dict)
                ],
            }
            for item in list(plan.get("capability_resolution_plan") or [])[:max_links]
            if isinstance(item, dict)
        ],
        "adaptive_sequence": [
            {
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "action": item.get("action", ""),
            }
            for item in list(plan.get("adaptive_sequence") or [])[:max_links]
            if isinstance(item, dict)
        ],
        "mixed_operation_sequence": [
            {
                "step": item.get("step", 0),
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "action_type": item.get("action_type", ""),
                "planned_call": {
                    "callable": (item.get("planned_call") or {}).get("callable", ""),
                    "implementation_status": (item.get("planned_call") or {}).get("implementation_status", ""),
                    "capability": (item.get("planned_call") or {}).get("capability", ""),
                    "host": (item.get("planned_call") or {}).get("host", ""),
                    "arguments": dict((item.get("planned_call") or {}).get("arguments") or {}),
                    "dependencies": list((item.get("planned_call") or {}).get("dependencies") or [])[:8],
                    "expected_outputs": list((item.get("planned_call") or {}).get("expected_outputs") or [])[:8],
                    "readback_validation": list((item.get("planned_call") or {}).get("readback_validation") or [])[:8],
                },
                "requires_network": bool(item.get("requires_network", False)),
                "requires_approval": bool(item.get("requires_approval", False)),
                "requires_license_check": bool(item.get("requires_license_check", False)),
                "report_sources": bool(item.get("report_sources", False)),
            }
            for item in list(plan.get("mixed_operation_sequence") or [])[:max_links * 3]
            if isinstance(item, dict)
        ],
        "operation_contracts": [
            {
                "id": item.get("id", ""),
                "action_type": item.get("action_type", ""),
                "capability": item.get("capability", ""),
                "execution_host": item.get("execution_host", ""),
                "provider_id": item.get("provider_id", ""),
                "callable": item.get("callable", ""),
                "call_arguments": dict(item.get("call_arguments") or {}),
                "call_dependencies": list(item.get("call_dependencies") or [])[:8],
                "validation_steps": list(item.get("validation_steps") or [])[:8],
                "planned_call": {
                    "callable": (item.get("planned_call") or {}).get("callable", item.get("callable", "")),
                    "implementation_status": (item.get("planned_call") or {}).get("implementation_status", ""),
                    "arguments": dict((item.get("planned_call") or {}).get("arguments") or item.get("call_arguments") or {}),
                    "dependencies": list((item.get("planned_call") or {}).get("dependencies") or item.get("call_dependencies") or [])[:8],
                    "readback_validation": list((item.get("planned_call") or {}).get("readback_validation") or item.get("validation_steps") or [])[:8],
                },
                "approval_policy": item.get("approval_policy", ""),
                "network_requirement": item.get("network_requirement", ""),
            }
            for item in list(plan.get("operation_contracts") or [])[:max_links * 2]
            if isinstance(item, dict)
        ],
        "mixed_operation_graph": {
            "framework": (plan.get("mixed_operation_graph") or {}).get("framework", ""),
            "base_graph": (plan.get("mixed_operation_graph") or {}).get("base_graph", ""),
            "node_count": len((plan.get("mixed_operation_graph") or {}).get("nodes") or []),
            "edge_count": len((plan.get("mixed_operation_graph") or {}).get("edges") or []),
            "supports": list((plan.get("mixed_operation_graph") or {}).get("supports") or [])[:8],
        },
        "canonical_action_graph": {
            "framework": "tech_connector.services.action_graph_service.ActionGraph",
            "intent": (plan.get("canonical_action_graph") or {}).get("intent", ""),
            "planner": (plan.get("canonical_action_graph") or {}).get("planner", ""),
            "action_count": len((plan.get("canonical_action_graph") or {}).get("actions") or []),
            "validation": (plan.get("canonical_action_graph") or {}).get("validation", {}),
        },
        "pipeline_materialization_plan": {
            "framework": (plan.get("pipeline_materialization_plan") or {}).get("framework", ""),
            "convertible": bool((plan.get("pipeline_materialization_plan") or {}).get("convertible", False)),
            "status": (plan.get("pipeline_materialization_plan") or {}).get("status", ""),
            "default_promotion_scope": (plan.get("pipeline_materialization_plan") or {}).get("default_promotion_scope", ""),
            "generated_function_root": (plan.get("pipeline_materialization_plan") or {}).get("generated_function_root", ""),
            "third_party_wrapper_root": (plan.get("pipeline_materialization_plan") or {}).get("third_party_wrapper_root", ""),
            "generated_callable_candidates": [
                {
                    "action_id": item.get("action_id", ""),
                    "capability": item.get("capability", ""),
                    "materialization_kind": item.get("materialization_kind", ""),
                    "status": item.get("status", ""),
                    "implementation_path": (item.get("implementation") or {}).get("path", ""),
                    "manifest_path": (item.get("manifest") or {}).get("path", ""),
                    "promotion_scope_default": item.get("promotion_scope_default", ""),
                    "trust_state": item.get("trust_state", ""),
                }
                for item in list((plan.get("pipeline_materialization_plan") or {}).get("generated_callable_candidates") or [])[:max_links]
                if isinstance(item, dict)
            ],
            "pipeline_node_candidates": [
                {
                    "action_id": item.get("action_id", ""),
                    "node_kind": item.get("node_kind", ""),
                    "pipeline_node_type": item.get("pipeline_node_type", ""),
                    "registered_callable": bool(item.get("registered_callable", False)),
                    "materializable": bool(item.get("materializable", False)),
                }
                for item in list((plan.get("pipeline_materialization_plan") or {}).get("pipeline_node_candidates") or [])[:max_links]
                if isinstance(item, dict)
            ],
        },
        "approval_gates": [
            {
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "requires_link": bool(item.get("requires_link", False)),
                "requires_fit_explanation": bool(item.get("requires_fit_explanation", False)),
                "requires_license_check": bool(item.get("requires_license_check", False)),
                "requires_user_approval": bool(item.get("requires_user_approval", False)),
            }
            for item in list(plan.get("approval_gates") or [])[:max_links]
            if isinstance(item, dict)
        ],
        "source_report_requirements": [
            {
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "report_links": bool(item.get("report_links", False)),
                "report_relevance": bool(item.get("report_relevance", False)),
                "report_knowledge_added": bool(item.get("report_knowledge_added", False)),
            }
            for item in list(plan.get("source_report_requirements") or [])[:max_links]
            if isinstance(item, dict)
        ],
        "planned_actions": list(plan.get("planned_actions") or [])[:max_actions],
        "test_plan": list(plan.get("test_plan") or [])[:max_tests],
        "learning_recommendations": list(plan.get("learning_recommendations") or [])[:max_learning],
    }


def render_goal_gap_plan(plan: dict[str, Any] | None, *, max_links: int = 5) -> str:
    if not plan:
        return ""
    formulation = dict(plan.get("problem_formulation") or {})
    lines = [
        "Goal gap plan:",
        f"Goal: {plan.get('goal', '')}",
        f"Next action: {plan.get('next_action', '')}",
    ]
    if formulation:
        lines.extend([
            "Problem formulation:",
            f"- {formulation.get('interpreted_problem', '')}",
            f"- deliverables={', '.join(formulation.get('deliverables') or [])}",
            f"- adequate={str(bool(formulation.get('adequate'))).lower()} confidence={float(formulation.get('confidence') or 0):.2f}",
        ])
    links = list(plan.get("missing_links") or [])
    if links:
        lines.append("Missing or unverified links:")
        for link in links[:max_links]:
            lines.append(f"- {link.get('label', '')}: {link.get('status', '')}")
    options = list(plan.get("resolution_options") or [])
    if options:
        lines.append("Top resolution options:")
        for option in options[:3]:
            lines.append(f"- {option.get('label', '')} ({option.get('confidence', 0):.2f})")
    sequence = list(plan.get("adaptive_sequence") or [])
    if sequence:
        lines.append("Adaptive sequence:")
        for item in sequence[:4]:
            lines.append(f"- {item.get('action', '')}: {item.get('capability', '')} via {item.get('strategy', '')}")
    gates = list(plan.get("approval_gates") or [])
    if gates:
        lines.append("Source review gates:")
        for gate in gates[:3]:
            lines.append(f"- {gate.get('strategy', '')}: show links/relevance before use")
    source_reports = list(plan.get("source_report_requirements") or [])
    if source_reports:
        lines.append("Knowledge source report:")
        for item in source_reports[:3]:
            lines.append(f"- {item.get('strategy', '')}: report links and relevance after research")
    mixed = list(plan.get("mixed_operation_sequence") or [])
    if mixed:
        lines.append("Mixed operations:")
        for item in mixed[:5]:
            planned_call = dict(item.get("planned_call") or {})
            call_arguments = dict(planned_call.get("arguments") or {})
            arg_keys = ", ".join(list(call_arguments.keys())[:6])
            callable_name = planned_call.get("callable", "")
            call_text = f" call={callable_name}" if callable_name else ""
            args_text = f" args=[{arg_keys}]" if arg_keys else ""
            lines.append(f"- {item.get('action_type', '')}: {item.get('capability', '')}{call_text}{args_text}")
    graph = dict(plan.get("mixed_operation_graph") or {})
    if graph:
        lines.append(
            f"Operation graph: {graph.get('base_graph', 'ActionGraph')} "
            f"nodes={len(graph.get('nodes') or [])} edges={len(graph.get('edges') or [])}"
        )
    materializer = dict(plan.get("pipeline_materialization_plan") or {})
    if materializer:
        lines.append("Pipeline materialization:")
        lines.append(
            f"- convertible={str(bool(materializer.get('convertible'))).lower()} "
            f"generated={len(materializer.get('generated_callable_candidates') or [])} "
            f"default_scope={materializer.get('default_promotion_scope', '')}"
        )
        for item in list(materializer.get("generated_callable_candidates") or [])[:max_links]:
            implementation = item.get("implementation") or {}
            lines.append(f"- {item.get('capability', '')}: {implementation.get('path', '')}")
    actions = list(plan.get("planned_actions") or [])
    if actions:
        lines.append("Planned actions:")
        lines.extend(f"- {item}" for item in actions[:4])
    tests = list(plan.get("test_plan") or [])
    if tests:
        lines.append("How to test:")
        lines.extend(f"- {item}" for item in tests[:4])
    outline = list(plan.get("report_outline") or [])
    if outline:
        lines.append("Report outline:")
        lines.extend(f"- {item}" for item in outline[:5])
    learning = list(plan.get("learning_recommendations") or [])
    if learning:
        lines.append("Learning loop:")
        lines.extend(f"- {item}" for item in learning[:3])
    return "\n".join(lines)
