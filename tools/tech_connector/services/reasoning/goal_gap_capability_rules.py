"""Goal-gap capability models, catalogs, and strategy selection rules."""
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
    return route in {"dcc_query", "dcc_execute", "function_execution", "project_search", "chat", "open_file"}


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
    if (direct_dcc_route or status != "known") and any(term in host_text for term in ("blender", "maya", "houdini", "motionbuilder", "substance", "unity", "unreal")):
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

    prompt = str(decision.get("prompt") or decision.get("original_prompt") or "").lower()
    online_animation_step = capability in {
        "blender_animation_source_scan",
        "online_animation_source",
    } and status != "known" and bool(
        re.search(r"\b(online|web|internet|research|find .*animation)\b", prompt)
    )
    if online_animation_step and decision.get("allow_external_research"):
        keys.insert(0, "web_knowledge_search")
        if allow_ingestion:
            keys.extend([
                "github_candidate_review",
                "download_or_ingest_asset",
                "register_capability",
            ])
    if capability == "blender_fbx_export" and "unreal" in prompt:
        keys.append("run_python_function")
    keys.append("validate_result")
    return list(_uniq(keys))
