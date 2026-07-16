"""Goal-driven capability gap planning.

This service is deterministic and intentionally lightweight. It does not execute
work or perform research. It turns a user goal into capability nodes, missing
links, gap resolution options, and learning recommendations so planning can account for
the real A-to-Z path instead of assuming a direct implementation step exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
        from services.problem_formulation_service import build_problem_formulation

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
            _node("compatible_skeleton", "Compatible character skeleton and animation blueprint", requires=("target character",), produces=("retarget target",), verification=("verify skeleton, mesh, and AnimBP paths")),
            _node("pose_search_or_plugin", "Pose Search / Motion Matching plugin capability", requires=("unreal version",), produces=("runtime query support",), verification=("verify plugin availability and enabled state")),
            _node("animation_database", "Animation database or pose-search schema", requires=("compatible animations", "pose search capability"), produces=("queryable animation set",), verification=("compile/load database asset")),
            _node("animation_metadata", "Animation metadata, tags, sync markers, or trajectory features", requires=("animation set",), produces=("search features",), verification=("inspect tags/features on candidate clips")),
            _node("runtime_integration", "Runtime integration from climbing state into motion matching query", requires=("movement state", "database", "AnimGraph insertion point"), produces=("playable integrated feature",), verification=("preview AnimGraph path and test state transition")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="official_pose_search",
                label="Use Unreal Pose Search / Motion Matching where available",
                confidence=0.9,
                steps=("verify plugin and engine version", "build/search database", "connect existing climbing state", "validate AnimGraph transition"),
                pros=("highest alignment with current Unreal architecture", "less custom runtime code"),
                cons=("requires compatible engine/plugin support and animation data"),
                research_hint="Official Unreal Pose Search / Motion Matching documentation",
            ),
            GapResolutionOption(
                key="simplified_state_machine_resolution",
                label="Build a staged climbing state-machine integration first",
                confidence=0.72,
                steps=("reuse current climbing state", "add metadata-driven clip selection", "defer full pose search until data exists"),
                pros=("testable without a full database", "preserves existing behavior"),
                cons=("not full motion matching"),
            ),
            GapResolutionOption(
                key="custom_runtime",
                label="Create a custom runtime matcher",
                confidence=0.45,
                steps=("define feature vectors", "sample animation poses", "build runtime query", "validate performance"),
                pros=("maximum control"),
                cons=("high risk and likely unnecessary if built-in tools exist"),
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
            _node("existing_movement_system", "Existing sprint/movement-state implementation", produces=("integration point",), verification=("find sprint input, movement component, Blueprint/C++/GAS path")),
            _node("stat_architecture", "Existing stat/component/GAS architecture", requires=("project scan",), produces=("preferred storage location",), verification=("identify reusable component/attribute system")),
            _node("stamina_contract", "Stamina data and events contract", requires=("max/drain/recovery requirements",), produces=("public UI/read events",), verification=("check callbacks/replication semantics")),
            _node("sprint_integration", "Integration with current sprint path", requires=("integration point", "stamina contract"), produces=("single sprint path",), verification=("drain/cancel/recover behavior checks")),
            _node("network_policy", "Replication/authority policy if networked", requires=("networked project detection",), produces=("minimal replicated state",), verification=("server authority and UI read path verified")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="reuse_existing_stat_system",
                label="Extend existing stat/GAS/component architecture",
                confidence=0.88,
                steps=("inspect existing systems", "extend matching component/attribute", "wire current sprint path", "validate thresholds and events"),
                pros=("lowest duplication", "fits project conventions"),
                cons=("requires accurate discovery before editing"),
            ),
            GapResolutionOption(
                key="new_component_resolution",
                label="Create a reusable stamina component and adapt sprint to it",
                confidence=0.72,
                steps=("create component", "add events/read API", "connect existing sprint", "validate movement-only drain"),
                pros=("portable and clear",),
                cons=("must avoid parallel sprint logic"),
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
            _node("symbol_inventory", "Function/class inventory", produces=("functions missing docstrings", "functions with incomplete params"), verification=("parse AST and signatures")),
            _node("style_contract", "Project docstring style contract", requires=("examples or existing conventions",), produces=("format rules",), verification=("compare with existing docstrings")),
            _node("safe_doc_update", "Doc-only update path", requires=("symbol inventory", "style contract"), produces=("updated docstrings",), verification=("syntax check modified files")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="ast_docstring_patch",
                label="Use AST-backed docstring patching",
                confidence=0.86,
                steps=("find missing/incomplete docstrings", "generate style-matched docs", "patch only docstrings", "run py_compile"),
                pros=("low behavioral risk", "can prioritize missing params"),
                cons=("semantic descriptions still need project context"),
            ),
        ),
        learning_recommendations=(
            "Persist the detected docstring style as a project documentation profile.",
            "Add a reusable docstring-completion pipeline node.",
        ),
    ),
    CapabilityPattern(
        key="cross_app.animation_transfer",
        labels=("Cross-application animation acquisition and transfer",),
        triggers=("blender", "animation online", "online animation", "import animation", "import into unreal", "fbx", "retarget"),
        required_chain=(
            _node("blender_context_operation", "Blender context/internal operation", produces=("prepared source scene or rig data",), verification=("query Blender scene/object/rig state")),
            _node("python_transform_helper", "Basic Python transform/helper step", requires=("source data",), produces=("normalized file or metadata",), verification=("helper return value and file existence")),
            _node("online_animation_source", "Online animation source candidate", requires=("search terms", "license constraints"), produces=("downloadable animation asset",), verification=("source link, relevance, and license recorded")),
            _node("asset_ingest", "Animation asset download/ingest", requires=("approved source",), produces=("local animation file",), verification=("file exists and format is supported")),
            _node("unreal_animation_import", "Unreal animation import", requires=("local animation file", "target skeleton/project"), produces=("imported Unreal animation asset",), verification=("asset exists in Content Browser and loads")),
            _node("post_import_tool", "Post-import internal tool operation", requires=("imported asset",), produces=("final connected/processed result",), verification=("tool result and affected asset state")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="internal_then_acquire_then_unreal",
                label="Run internal prep, acquire animation with approval, import into Unreal, then continue tools",
                confidence=0.76,
                steps=("run Blender/internal prep", "run Python normalization", "find animation source and report links/relevance", "pause for ingest approval/license", "import into Unreal", "run post-import tool and validate"),
                pros=("handles mixed app workflow explicitly", "keeps external asset approval visible"),
                cons=("depends on source availability and target skeleton compatibility"),
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
    matches: list[CapabilityPattern] = []
    for pattern in PATTERNS:
        score = 0
        for trigger in pattern.triggers:
            if trigger in lower or trigger in route_blob:
                score += 1
        if score:
            matches.append(pattern)
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
            _node("goal_normalization", "Normalize user goal from prompt plus thread context", produces=("success criteria",), verification=("goal and constraints are explicit")),
            _node("current_capability_check", "Check current capability graph and local project facts", requires=("project/tool context",), produces=("known capabilities", "missing links"), verification=("evidence has source paths or provider metadata")),
            _node("gap_discovery", "Discover intermediate capabilities needed to connect known A to requested Z", requires=("known capabilities", "goal"), produces=("resolution candidates",), verification=("each missing link has prerequisites and validation")),
            _node("option_ranking", "Rank resolution options by fit, safety, confidence, and validation path", requires=("resolution candidates",), produces=("recommended path",), verification=("tradeoffs and fallback are visible")),
            _node("learning_capture", "Capture reusable technique and future capability recommendation", requires=("completed or blocked plan",), produces=("knowledge update recommendation",), verification=("recommendation has source/evidence and is user-approvable")),
        ),
        resolution_options=(
            GapResolutionOption(
                key="compose_existing_capabilities",
                label="Compose existing local capabilities before creating new ones",
                confidence=0.78,
                steps=("inspect project/tool context", "find reusable operations", "insert missing prerequisite steps", "validate result"),
                pros=("avoids unnecessary new systems", "works with project conventions"),
                cons=("depends on index/host context quality"),
            ),
            GapResolutionOption(
                key="research_then_persist",
                label="Research missing techniques, then persist structured local knowledge",
                confidence=0.66,
                steps=("identify missing capability", "request/perform authoritative research if allowed", "convert result to local playbook/capability", "use it in the plan"),
                pros=("improves future attempts",),
                cons=("requires source permission and validation"),
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
    return route in {"dcc_execute", "function_execution", "target_discovery", "project_search", "chat", "open_file"}


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


def _known_capability_evidence(decision: dict[str, Any]) -> tuple[str, ...]:
    evidence: list[str] = []
    for item in list(decision.get("context_resolvers") or [])[:6]:
        evidence.append(f"context resolver: {item}")
    for item in list(decision.get("deterministic_steps") or [])[:6]:
        evidence.append(f"deterministic step: {item}")
    for item in list(decision.get("capability_gaps") or [])[:6]:
        evidence.append(f"known gap: {item}")
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
        plan.append(
            {
                "capability": node.key,
                "label": node.label,
                "status": node.status,
                "chosen_strategy": chosen,
                "strategies": [strategy.to_dict() for strategy in strategies[:max_strategies_per_node]],
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
        elif chosen in {"github_ingest", "plugin_marketplace"}:
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
    elif strategy == "generate_new_code":
        keys.extend(["generate_code_or_wrapper", "register_capability"])
    elif strategy == "ask_user":
        keys.append("validate_result")
    else:
        keys.append("execute_internal_function")

    host_text = f"{label} {capability}"
    if status != "known" and any(term in host_text for term in ("blender", "maya", "houdini", "motionbuilder", "substance", "unity", "unreal")):
        keys.insert(0, "run_dcc_operation")
    if "python" in host_text or "wrapper" in host_text:
        keys.append("run_python_function")
    if allow_ingestion and strategy in {"github_ingest", "plugin_marketplace"} and any(term in label for term in ("animation", "fbx", "asset", "motion", "clip")):
        keys.append("download_or_ingest_asset")
    if (
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


def _mixed_operation_sequence(adaptive_sequence: list[dict[str, Any]], decision: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    decision = dict(decision or {})
    steps: list[dict[str, Any]] = []
    index = 1
    for item in adaptive_sequence:
        for action_key in _action_keys_for_sequence_item(item, decision):
            action_type = _action_type_by_key(action_key)
            steps.append(
                {
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
            )
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
    return "tech_connector"


def _operation_action_contracts(mixed_sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for item in mixed_sequence:
        action_type = str(item.get("action_type") or "")
        capability = str(item.get("capability") or "")
        requires_network = bool(item.get("requires_network", False))
        requires_approval = bool(item.get("requires_approval", False))
        requires_license = bool(item.get("requires_license_check", False))
        contracts.append(
            {
                "id": f"action_{int(item.get('step') or 0):03d}_{action_type}",
                "action_type": action_type,
                "capability": capability,
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
                    "requires_snapshot": action_type in {"import_unreal_asset", "download_or_ingest_asset", "generate_code_or_wrapper"},
                },
                "validation_steps": list(item.get("validates_with") or []),
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
        "base_graph": "services.action_graph_service.ActionGraph",
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
                "operation_contract": contract,
            },
            "input": {
                "capability": contract.get("capability", ""),
                "provider_id": contract.get("provider_id", ""),
                "execution_context": contract.get("execution_context", {}),
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
        from services.action_graph_service import normalize_action_graph, validate_action_graph

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
        "base_graph": graph.get("base_graph", "services.action_graph_service.ActionGraph"),
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
            "framework": "services.action_graph_service.ActionGraph",
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
    """Build an A-to-Z plan only after the problem is adequately formulated."""
    decision = dict(decision or {})
    problem_formulation = _build_problem_formulation(prompt, decision)
    decision["problem_formulation"] = problem_formulation

    # Capability matching may use the original wording, but the formulated
    # problem is authoritative for goal, prerequisites, success, and whether
    # execution is allowed to continue.
    patterns = _matched_patterns(prompt, decision)
    if not patterns:
        # A request is only "quick direct" after formulation confirms that it
        # is actually an execution/direct-action problem rather than a source
        # question containing executable words.
        quick_allowed = (
            str(problem_formulation.get("action_mode") or "") in {"execute", "mutate"}
            and bool(problem_formulation.get("adequate"))
            and not _problem_formulation_requires_pause(problem_formulation)
        )
        patterns = [_quick_direct_pattern(prompt, decision)] if quick_allowed and _is_quick_direct_action(decision) else [_generic_pattern(prompt, decision)]

    goal = str(
        problem_formulation.get("interpreted_problem")
        or problem_formulation.get("desired_outcome")
        or _goal_from_prompt(prompt)
    )
    known_evidence = _known_capability_evidence(decision)
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
    nodes.extend(_capability_nodes_from_problem_formulation(problem_formulation))
    options: list[GapResolutionOption] = []
    questions: list[str] = []
    learning: list[str] = []
    labels: list[str] = []

    for pattern in patterns:
        labels.extend(pattern.labels)
        nodes.extend(pattern.required_chain)
        options.extend(pattern.resolution_options)
        questions.extend(pattern.questions)
        learning.extend(pattern.learning_recommendations)

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
    operation_contracts = _operation_action_contracts(mixed_operation_sequence)
    mixed_operation_graph = _mixed_operation_graph(operation_contracts)
    pipeline_materialization_plan = _pipeline_materialization_plan(operation_contracts, mixed_operation_graph)
    canonical_action_graph = _canonical_action_graph(
        goal,
        operation_contracts,
        mixed_operation_graph,
        pipeline_materialization_plan,
    )
    pipeline_materialization_plan["canonical_action_graph"] = {
        "framework": "services.action_graph_service.ActionGraph",
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
            lines.append(f"- {item.get('action_type')}: {item.get('capability')} via {item.get('strategy')}{flag_text}")
    if plan.get("operation_contracts"):
        lines.append("Universal action contracts:")
        for contract in plan["operation_contracts"][:6]:
            inputs = ", ".join(item.get("artifact_type", "") for item in contract.get("inputs", [])[:3])
            outputs = ", ".join(item.get("artifact_type", "") for item in contract.get("outputs", [])[:3])
            lines.append(
                f"- {contract.get('id')}: {contract.get('action_type')} on {contract.get('execution_host')} "
                f"inputs=[{inputs}] outputs=[{outputs}]"
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
            "framework": "services.action_graph_service.ActionGraph",
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
            lines.append(f"- {item.get('action_type', '')}: {item.get('capability', '')}")
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
