"""Local known-practice playbooks for common DCC/engine workflows.

These are intentionally compact. They give the model a known recipe before it
starts reasoning, so common production tasks do not become open-ended planning.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class TaskPlaybook:
    key: str
    title: str
    hosts: tuple[str, ...]
    required_terms: tuple[str, ...]
    optional_terms: tuple[str, ...]
    summary: str
    steps: tuple[str, ...]
    action_path: tuple[str, ...] = ()
    prefer_operations: tuple[str, ...] = ()
    ask_when_missing: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()


@dataclass(frozen=True)
class BestPracticeAssessment:
    matched_playbooks: tuple[TaskPlaybook, ...]
    confidence: str
    reasons: tuple[str, ...]
    should_offer_research: bool
    research_query: str


DEFAULT_ACTION_PATH = (
    "Understand the user's goal using current prompt plus thread/project/host context.",
    "Resolve exact target host, asset/object, selection, and missing slots before mutation.",
    "Choose the registered host operation or host-native API path that matches the known practice.",
    "Execute the smallest safe change, preserving existing authored data.",
    "Validate by querying/compiling/inspecting the changed host state.",
    "Report exact changes, unresolved assumptions, and next safe actions.",
)


RISK_TERMS = (
    "delete",
    "overwrite",
    "replace",
    "rename",
    "batch",
    "migrate",
    "upgrade",
    "destructive",
    "production",
    "publish",
    "release",
    "source control",
    "checkout",
    "commit",
    "merge",
    "history",
    "reference",
    "skincluster",
    "retarget",
    "bake",
    "save",
)

QUALITY_TERMS = (
    "best practice",
    "recommended",
    "safest",
    "standard",
    "production ready",
    "proper",
    "right way",
    "maintainable",
    "performant",
    "current",
    "official",
)

PROVIDER_ALIASES = {
    "ue": "unreal",
    "ue5": "unreal",
    "unreal engine": "unreal",
    "maya": "maya",
    "blender": "blender",
    "houdini": "houdini",
    "motionbuilder": "motionbuilder",
    "substance painter": "substance_painter",
    "unity": "unity",
    "github": "github",
    "perforce": "perforce",
    "slack": "slack",
    "confluence": "confluence",
    "jira": "jira",
}


TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "unreal": ("ue", "ue5", "engine"),
    "niagara": ("niagra", "particle", "particles", "particle system", "vfx", "fx", "effect", "effects"),
    "emitter": ("particle emitter", "effect emitter", "vfx emitter"),
    "attach": ("parent", "socket", "mount", "bind to", "stick to", "follow"),
    "hand": ("palm", "wrist", "hand_r", "hand_l", "right hand", "left hand"),
    "socket": ("bone", "joint", "attach point", "mount point"),
    "anim": ("animation", "montage", "anim notify", "animation notify", "notify state", "animation event", "montage event"),
    "notify": ("anim notify", "animation notify", "notify state", "animation event", "montage event", "cue", "trigger"),
    "parameter": ("property", "properties", "variable", "variables", "exposed value", "user parameter"),
    "rig": ("control rig", "skeleton", "joint chain", "character setup"),
    "skin": ("bind skin", "skinning", "weights", "skincluster", "deform"),
    "constraint": ("parent constraint", "orient constraint", "point constraint", "matrix constraint"),
    "material": ("shader", "surface", "lookdev", "texture"),
    "mesh": ("geo", "geometry", "model", "object"),
    "mocap": ("motion capture", "take", "retarget", "plot"),
    "houdini": ("hda", "sop", "dop", "lop", "procedural"),
    "substance": ("painter", "substance painter", "spp", "texture set"),
    "unity": ("gameobject", "prefab", "vfx graph", "particle system"),
}


def thread_context_text(session: Iterable[dict] | None, max_messages: int = 8, max_chars: int = 5000) -> str:
    messages = []
    for message in list(session or [])[-max_messages:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "message")
        content = message.get("content") or ""
        if isinstance(content, list):
            content = " ".join(str(item.get("text") or item.get("content") or item) if isinstance(item, dict) else str(item) for item in content)
        text = str(content).strip()
        if not text:
            continue
        messages.append(f"{role}: {text}")
    joined = "\n".join(messages)
    return joined[-max_chars:]


def combined_task_text(text: str, *, thread_context: str = "", project_context: str = "", tool_context: str = "") -> str:
    parts = [
        "CURRENT REQUEST:",
        text or "",
    ]
    if thread_context:
        parts.extend(["RECENT THREAD CONTEXT:", thread_context])
    if project_context:
        parts.extend(["PROJECT CONTEXT:", project_context])
    if tool_context:
        parts.extend(["TOOL/HOST CONTEXT:", tool_context])
    return "\n".join(parts)


def _expanded_query(text: str) -> str:
    expanded = [text or ""]
    lower = (text or "").lower()
    token_set = set(re.findall(r"[a-z0-9_]+", lower))
    for canonical, aliases in TERM_ALIASES.items():
        alias_hit = canonical in token_set or canonical in lower
        if not alias_hit:
            alias_hit = any(alias in lower for alias in aliases)
        if alias_hit:
            expanded.append(canonical)
            expanded.extend(aliases)
    return " ".join(expanded)


PLAYBOOKS: tuple[TaskPlaybook, ...] = (
    TaskPlaybook(
        key="dcc.general.safe_scene_edit",
        title="General DCC safe scene edit",
        hosts=("maya", "blender", "motionbuilder", "houdini", "substance_painter", "unity", "unreal"),
        required_terms=("create",),
        optional_terms=("modify", "edit", "setup", "build", "asset", "scene", "selection", "material", "rig", "animation"),
        summary=(
            "For DCC edits, inspect current selection/assets first, use host-native operations, make the smallest reversible change, "
            "and validate the result before reporting success."
        ),
        steps=(
            "Detect the active host and current selection/context before creating new objects.",
            "Resolve exact object, asset, material, bone, socket, or file names instead of guessing.",
            "Prefer host-native APIs and registered bridge operations over generated free-form scripts.",
            "Use non-destructive or additive edits where possible, and preserve user-authored data.",
            "Validate by querying the changed objects/assets after mutation.",
            "Report exact names, paths, changed properties, and any unresolved assumptions.",
        ),
        action_path=DEFAULT_ACTION_PATH,
        ask_when_missing=("target object/asset", "destructive confirmation", "required output path or host scene context"),
        avoid=(
            "Do not invent scene object names.",
            "Do not overwrite authored assets without confirmation.",
            "Do not skip validation after mutating a DCC scene.",
        ),
    ),
    TaskPlaybook(
        key="unreal.niagara.character_hand_anim_notify",
        title="Unreal Niagara attached to character hand and triggered by animation notify",
        hosts=("unreal",),
        required_terms=("niagara",),
        optional_terms=(
            "emitter",
            "system",
            "attach",
            "hand",
            "socket",
            "bone",
            "character",
            "anim",
            "animation",
            "notify",
            "montage",
            "properties",
            "parameter",
        ),
        summary=(
            "Use a Niagara System asset exposed through user parameters, attach/spawn it on the character mesh socket or bone, "
            "and trigger activation from an Anim Notify or Anim Notify State. Do not treat this as generic planning."
        ),
        steps=(
            "Resolve the character Blueprint or selected actor and identify the skeletal mesh component.",
            "Resolve or create a Niagara System asset; prefer a system over a raw emitter when it will be spawned/attached.",
            "Expose animatable values as Niagara User Parameters such as color, intensity, size, rate, or lifetime.",
            "Attach the Niagara component to the hand socket/bone, defaulting to hand_r/hand_l only when the prompt says which hand.",
            "Trigger activate/deactivate or spawn from an Anim Notify / Anim Notify State on the relevant animation or montage.",
            "Set user parameters before activation so animation timing can drive visible properties.",
            "Compile/save touched Blueprint/Niagara assets and report exact assets, sockets, parameters, and validation result.",
        ),
        action_path=(
            "Infer this as a Niagara character-attachment workflow even if the user says particle/VFX/effect.",
            "Resolve character/mesh/socket/animation context from thread, selection, and project assets.",
            "Create or resolve the Niagara System and expose animatable User Parameters.",
            "Attach or spawn the Niagara component on the hand socket/bone.",
            "Wire activation and parameter updates through Anim Notify / Anim Notify State timing.",
            "Compile/save touched assets and validate attachment, parameters, and notify trigger.",
        ),
        prefer_operations=(
            "niagara.create_emitter",
            "niagara.add_to_level",
            "niagara.attach_to_selected_actor",
            "niagara.set_user_parameter",
            "niagara.set_module_input",
            "blueprint.compile",
        ),
        ask_when_missing=(
            "target character or selected actor",
            "left/right hand or socket/bone name",
            "Niagara asset path/name",
            "animation sequence or montage for the notify",
            "which properties should be animatable",
        ),
        avoid=(
            "Do not invent asset paths, socket names, or animation assets.",
            "Do not create a detached level-only effect when the request says attach to the character.",
            "Do not bury missing required choices in a broad plan; ask concise slot questions.",
        ),
    ),
    TaskPlaybook(
        key="unreal.niagara.general",
        title="Unreal Niagara system/emitter edit",
        hosts=("unreal",),
        required_terms=("niagara",),
        optional_terms=("emitter", "system", "particle", "vfx", "parameter", "module", "renderer"),
        summary="Use registered Niagara operations and inspect existing systems before mutating emitter/module/renderer settings.",
        steps=(
            "Resolve the target Niagara System or Emitter asset.",
            "Inspect emitters, user parameters, renderer properties, and module inputs before editing.",
            "Prefer exposed User Parameters for values users expect to animate or drive from Blueprint.",
            "Apply the smallest operation that matches the requested change.",
            "Compile/save and report validation details.",
        ),
        action_path=(
            "Classify the request as Niagara even when phrased as particles/VFX/effects.",
            "Inspect the target system/emitter before choosing mutation operations.",
            "Resolve reflected user parameters, renderer properties, or module inputs.",
            "Apply the smallest registered Niagara operation.",
            "Compile/save and report validation details.",
        ),
        prefer_operations=(
            "niagara.inspect_system",
            "niagara.list_module_inputs",
            "niagara.set_user_parameter",
            "niagara.set_renderer_property",
            "niagara.set_module_input",
        ),
        ask_when_missing=("target Niagara asset", "property/module/input name", "value"),
        avoid=("Do not guess reflected property names; inspect/list first.",),
    ),
    TaskPlaybook(
        key="unreal.blueprint.character_feature",
        title="Unreal Blueprint character feature implementation",
        hosts=("unreal",),
        required_terms=("blueprint",),
        optional_terms=("character", "component", "ability", "input", "anim", "montage", "notify", "compile", "socket"),
        summary="Use a component or focused Blueprint graph change, inspect the existing Blueprint first, then compile and validate.",
        steps=(
            "Resolve the target Blueprint asset and inspect existing components, variables, events, and graph structure.",
            "Prefer an Actor Component for reusable gameplay logic; keep character Blueprint glue small.",
            "Use existing input/action mappings, animation montages, sockets, and components when present.",
            "Create explicit variables for tunable values and expose only user-facing controls.",
            "Compile the Blueprint, inspect compile results, save only touched assets, and report graph changes.",
        ),
        action_path=(
            "Resolve target Blueprint and current asset context.",
            "Inspect graph/components before edits.",
            "Choose component, variable, event, or graph operation based on existing structure.",
            "Apply focused Blueprint changes.",
            "Compile, validate, save, and report exact graph/component changes.",
        ),
        prefer_operations=("blueprint.inspect_graph", "blueprint.add_component", "blueprint.set_variable", "blueprint.compile"),
        ask_when_missing=("target Blueprint", "input/action trigger", "asset references", "whether to create reusable component"),
        avoid=("Do not create duplicate event graphs or orphan components.", "Do not assume C++ bridge support unless enabled."),
    ),
    TaskPlaybook(
        key="maya.rigging.control_rig_skin",
        title="Maya character rigging and skinning",
        hosts=("maya",),
        required_terms=(),
        optional_terms=("joint", "skin", "bind", "control", "constraint", "ik", "fk", "mesh", "curve", "root"),
        summary="Use clean joint/control hierarchy, named constraints, bind validation, and reversible setup steps.",
        steps=(
            "Inspect current selection and existing joints, mesh, skinCluster, controls, and namespaces.",
            "Create or reuse a clean joint hierarchy with predictable side/name tokens.",
            "Build NURBS controls with zero groups and freeze/lock only the appropriate channels.",
            "Use parent/orient/point constraints or matrix connections deliberately; keep maintainOffset explicit.",
            "Bind or update skinCluster only after confirming target mesh and influences.",
            "Validate deformation by checking skinCluster influences, missing weights, constraints, and driven channels.",
        ),
        action_path=(
            "Resolve rig target from selection/thread/project symbols.",
            "Inspect existing hierarchy, controls, skinCluster, and constraints.",
            "Choose control/constraint/skin operation without disturbing authored data.",
            "Apply named, reversible rig edits.",
            "Validate hierarchy, deformation, constraints, and locked/driven channels.",
        ),
        prefer_operations=("rig.create_control", "constraints.create", "skin.bind", "node.connect_attr", "api.call"),
        ask_when_missing=("mesh", "root joint", "control naming/side", "whether to preserve existing skin weights"),
        avoid=("Do not delete existing skinClusters or constraints without confirmation.", "Do not guess left/right side from ambiguous names."),
    ),
    TaskPlaybook(
        key="maya.animation_scene_tools",
        title="Maya animation and scene tooling",
        hosts=("maya",),
        required_terms=(),
        optional_terms=("key", "timeline", "constraint", "pose", "bake", "motion", "curve", "joint", "control"),
        summary="Preserve animation data, work on explicit ranges, and bake/constraint only when the target controls are known.",
        steps=(
            "Inspect selected controls/joints and current playback range.",
            "Resolve whether the edit should affect keys, constraints, animation layers, or baked transforms.",
            "Use animation layers or duplicate buffers when testing destructive motion edits.",
            "When baking, set an explicit frame range and preserve original source where possible.",
            "Validate resulting keyframes, tangents, constraints, and transform channels.",
        ),
        action_path=(
            "Resolve animation target and frame range from prompt/thread/scene.",
            "Inspect keys, layers, constraints, and selected controls.",
            "Choose key/layer/constraint/bake path explicitly.",
            "Apply animation edit with preservation strategy.",
            "Validate keyframes, tangents, constraints, and playback result.",
        ),
        prefer_operations=("constraints.create", "node.connect_attr", "api.call"),
        ask_when_missing=("target controls/joints", "frame range", "bake vs live constraint", "preserve original animation"),
        avoid=("Do not bake entire scenes by default.", "Do not change tangents or layers unless requested."),
    ),
    TaskPlaybook(
        key="blender.modeling_material_nodes",
        title="Blender modeling and material node workflow",
        hosts=("blender",),
        required_terms=(),
        optional_terms=("mesh", "model", "material", "shader", "node", "geometry", "modifier", "uv", "bpy"),
        summary="Use bpy-native operations, preserve object data, and prefer modifiers/nodes for editable procedural results.",
        steps=(
            "Inspect selected objects, active collection, materials, modifiers, and object mode.",
            "Create or modify mesh data with explicit names and link objects to the intended collection.",
            "Prefer modifiers/Geometry Nodes for procedural edits the user may want to iterate.",
            "Build material node trees with named nodes and exposed parameters instead of opaque values.",
            "Validate object existence, transforms, material slots, modifier stack, and scene selection after changes.",
        ),
        action_path=(
            "Resolve target object/collection/material from context.",
            "Inspect object mode, selected objects, material slots, and modifiers.",
            "Choose bpy operation, modifier, or node-tree path.",
            "Apply editable/non-destructive change when possible.",
            "Validate object, material, modifier, and selection state.",
        ),
        prefer_operations=("modeling.create_primitive", "material.create", "api.call"),
        ask_when_missing=("target object/collection", "modifier vs applied mesh", "material name", "units/scale"),
        avoid=("Do not apply destructive modifiers unless requested.", "Do not leave objects unnamed or unlinked."),
    ),
    TaskPlaybook(
        key="houdini.procedural_fx",
        title="Houdini procedural FX / SOP workflow",
        hosts=("houdini",),
        required_terms=(),
        optional_terms=("sop", "node", "fx", "simulation", "pyro", "vellum", "geo", "attribute", "parameter"),
        summary="Build procedural node networks with named nodes, explicit attributes, and cache/sim boundaries.",
        steps=(
            "Resolve the target network path and current selection before adding nodes.",
            "Create named SOP/DOP/LOP nodes with stable positions and comments for generated networks.",
            "Prefer attribute-driven controls and promoted parameters for artist-editable setups.",
            "Separate source geometry, simulation, cache, and render prep into readable subnet sections.",
            "Validate node creation, parameter values, connections, cook errors, and output geometry.",
        ),
        action_path=(
            "Resolve network path and input geometry.",
            "Inspect selected/current node graph and cook state.",
            "Choose SOP/DOP/LOP/node-network path with promoted controls.",
            "Build named procedural nodes and connections.",
            "Validate cook errors, parameters, connections, and output geometry.",
        ),
        prefer_operations=("api.call",),
        ask_when_missing=("network path", "input geometry", "sim/cache expectations", "render/export target"),
        avoid=("Do not force recooks of heavy sims without confirmation.", "Do not bury generated nodes in /obj without naming."),
    ),
    TaskPlaybook(
        key="motionbuilder.retarget_mocap",
        title="MotionBuilder retargeting and mocap cleanup",
        hosts=("motionbuilder",),
        required_terms=(),
        optional_terms=("retarget", "mocap", "character", "take", "plot", "constraint", "skeleton", "animation"),
        summary="Preserve takes, characterize before retargeting, and validate plotting/constraints explicitly.",
        steps=(
            "Inspect current characters, skeletons, takes, story clips, and selected models.",
            "Verify source and target characterization before retargeting.",
            "Use constraints or control rigs only after confirming source/target mapping.",
            "Plot animation to the correct target and take, preserving the original take when possible.",
            "Validate frame range, plotted keys, foot/hand contacts, and active character mapping.",
        ),
        action_path=(
            "Resolve source/target character and take context.",
            "Inspect characterization, story clips, constraints, and frame range.",
            "Choose retarget, constraint, or plot path.",
            "Preserve source take and apply retarget/plot deliberately.",
            "Validate active character mapping, plotted keys, and contacts.",
        ),
        prefer_operations=("api.call",),
        ask_when_missing=("source character", "target character", "take/frame range", "plot destination"),
        avoid=("Do not overwrite original mocap takes by default.", "Do not retarget uncharacterized skeletons."),
    ),
    TaskPlaybook(
        key="substance_painter.material_texture_export",
        title="Substance Painter material authoring and texture export",
        hosts=("substance_painter",),
        required_terms=(),
        optional_terms=("material", "texture", "export", "paint", "layer", "mask", "smart material", "preset"),
        summary="Use project texture sets/layers deliberately and export through named presets to the expected DCC/engine target.",
        steps=(
            "Inspect open project, texture sets, selected stack/layers, and export presets.",
            "Create layers, masks, and smart materials with clear names and non-destructive structure.",
            "Keep channel/bit-depth/color-space choices aligned with the target engine/DCC.",
            "Export using an explicit preset and output path; do not assume packed-map layout.",
            "Validate exported files, texture set names, and missing maps.",
        ),
        action_path=(
            "Resolve texture set, layer stack, preset, and export target.",
            "Inspect current project/layers/channels.",
            "Choose layer/material/mask/export path.",
            "Apply non-destructive material or texture changes.",
            "Validate exported maps, channel packing, and file outputs.",
        ),
        prefer_operations=("api.call",),
        ask_when_missing=("texture set", "export preset", "output directory", "target engine shader convention"),
        avoid=("Do not overwrite exported textures without confirmation.", "Do not guess ORM/RMA channel packing."),
    ),
    TaskPlaybook(
        key="unity.gameobject_prefab_vfx",
        title="Unity GameObject, prefab, and VFX setup",
        hosts=("unity",),
        required_terms=(),
        optional_terms=("gameobject", "prefab", "vfx", "particle", "component", "animation", "script", "material"),
        summary="Use serialized components/prefabs, preserve scene/prefab overrides, and validate references after edits.",
        steps=(
            "Resolve active scene, selected GameObjects, prefab stage, and target asset paths.",
            "Add or edit components with serialized property names, not guessed field labels.",
            "Prefer prefab variants or components for reusable behavior instead of scene-only edits.",
            "Wire animation/events/VFX references explicitly and keep public fields assignable.",
            "Validate object/component existence, missing references, prefab save state, and console errors.",
        ),
        action_path=(
            "Resolve scene/prefab/GameObject and target component context.",
            "Inspect selected objects, prefab stage, serialized fields, and references.",
            "Choose component/prefab/VFX/script operation path.",
            "Apply serialized changes while preserving prefab links.",
            "Validate components, references, prefab save state, and console errors.",
        ),
        prefer_operations=("api.call",),
        ask_when_missing=("target GameObject/prefab", "component type", "asset reference", "scene vs prefab edit"),
        avoid=("Do not break prefab links unless requested.", "Do not leave missing script/reference slots."),
    ),
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", _expanded_query(text).lower()))


def _phrase_present(text: str, phrase: str, tokens: set[str]) -> bool:
    expanded = _expanded_query(text).lower()
    phrase_l = phrase.lower()
    if " " in phrase_l:
        return phrase_l in expanded
    return phrase_l in tokens


def score_playbook(playbook: TaskPlaybook, text: str, host: str = "", *, current_text: str = "") -> int:
    token_set = _tokens(text)
    current_tokens = _tokens(current_text or text)
    host_l = (host or "").lower()
    score = 0
    if host_l and host_l in playbook.hosts:
        score += 4
    elif host_l and host_l not in playbook.hosts:
        return 0
    missing_required = [
        term for term in playbook.required_terms
        if not _phrase_present(text, term, token_set)
    ]
    if missing_required:
        return 0
    optional_hits = sum(1 for term in playbook.optional_terms if _phrase_present(text, term, token_set))
    if not playbook.required_terms and optional_hits == 0:
        return 0
    score += 6 * len(playbook.required_terms)
    score += 2 * optional_hits
    score += sum(1 for term in playbook.optional_terms if _phrase_present(current_text or text, term, current_tokens))
    return score


def matching_playbooks(
    text: str,
    host: str = "",
    limit: int = 2,
    *,
    thread_context: str = "",
    project_context: str = "",
    tool_context: str = "",
) -> list[TaskPlaybook]:
    combined = combined_task_text(
        text,
        thread_context=thread_context,
        project_context=project_context,
        tool_context=tool_context,
    )
    scored = [
        (score_playbook(playbook, combined, host, current_text=text), playbook)
        for playbook in PLAYBOOKS
    ]
    ranked = [playbook for score, playbook in sorted(scored, key=lambda item: item[0], reverse=True) if score > 0]
    return ranked[:max(1, limit)]


def _detect_provider(text: str, host: str = "") -> str:
    if host:
        return PROVIDER_ALIASES.get(host.lower(), host.lower())
    lower = (text or "").lower()
    for alias, provider in sorted(PROVIDER_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])", lower):
            return provider
    return ""


def _detect_version(text: str) -> str:
    version_patterns = (
        r"\b(?:unreal|ue)\s*(?:engine)?\s*(5(?:\.\d+)?)\b",
        r"\bmaya\s*(20\d{2})\b",
        r"\bblender\s*(\d+(?:\.\d+)?)\b",
        r"\bhoudini\s*(\d+(?:\.\d+)?)\b",
        r"\bunity\s*(20\d{2}(?:\.\d+)?)\b",
    )
    lower = (text or "").lower()
    for pattern in version_patterns:
        match = re.search(pattern, lower)
        if match:
            return match.group(1)
    generic = re.search(r"\b(20\d{2}|5\.\d+|\d+\.\d+\.\d+)\b", lower)
    return generic.group(1) if generic else ""


def _hits(text: str, phrases: Iterable[str]) -> list[str]:
    lower = (text or "").lower()
    return [phrase for phrase in phrases if phrase in lower]


def best_practice_research_query(
    text: str,
    host: str = "",
    *,
    thread_context: str = "",
    project_context: str = "",
    tool_context: str = "",
) -> str:
    combined = "\n".join(
        part for part in (text or "", thread_context, project_context, tool_context) if part
    )
    provider = _detect_provider(combined, host)
    version = _detect_version(combined)
    tokens = [
        token
        for token in re.findall(r"[a-zA-Z0-9_./:-]+", _expanded_query(combined))
        if len(token) > 2
    ]
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "into", "what", "would",
        "could", "should", "make", "able", "want", "user", "current", "request",
        "recent", "thread", "context", "project", "tool", "host",
    }
    keywords = []
    for token in tokens:
        norm = token.lower()
        if norm in stopwords or norm in keywords:
            continue
        keywords.append(norm)
        if len(keywords) >= 14:
            break
    parts = []
    if provider:
        parts.append(provider.replace("_", " "))
    if version:
        parts.append(version)
    parts.extend(keywords)
    parts.extend(("official docs", "api reference", "best practices"))
    return " ".join(parts)


def assess_best_practice_coverage(
    text: str,
    host: str = "",
    limit: int = 3,
    *,
    thread_context: str = "",
    project_context: str = "",
    tool_context: str = "",
) -> BestPracticeAssessment:
    combined = combined_task_text(
        text,
        thread_context=thread_context,
        project_context=project_context,
        tool_context=tool_context,
    )
    raw_context = "\n".join(
        part for part in (text or "", thread_context, project_context, tool_context) if part
    )
    playbooks = tuple(
        matching_playbooks(
            text,
            host=host,
            limit=limit,
            thread_context=thread_context,
            project_context=project_context,
            tool_context=tool_context,
        )
    )
    provider = _detect_provider(combined, host)
    version = _detect_version(combined)
    risk_hits = _hits(raw_context, RISK_TERMS)
    quality_hits = _hits(raw_context, QUALITY_TERMS)
    reasons: list[str] = []
    if not playbooks:
        reasons.append("No local provider-specific playbook matched the request.")
    if provider and not playbooks:
        reasons.append(f"Provider context appears to be {provider}, but local guidance is incomplete.")
    if version:
        reasons.append(f"The request appears version-specific ({version}); verify current API guidance before relying on general rules.")
    if risk_hits:
        reasons.append("The task includes risk-sensitive operations: " + ", ".join(risk_hits[:5]) + ".")
    if quality_hits:
        reasons.append("The user requested a recommended or production-quality approach.")

    if playbooks and not version and not risk_hits:
        confidence = "high"
    elif playbooks:
        confidence = "medium"
    else:
        confidence = "low"

    has_best_practice_signal = bool(provider or version or risk_hits or quality_hits)
    should_offer = bool(
        (not playbooks and has_best_practice_signal)
        or version
        or risk_hits
        or quality_hits
    )
    if not reasons and playbooks:
        reasons.append("Local known-practice playbooks cover the request.")

    return BestPracticeAssessment(
        matched_playbooks=playbooks,
        confidence=confidence,
        reasons=tuple(reasons),
        should_offer_research=should_offer,
        research_query=best_practice_research_query(
            text,
            host=host,
            thread_context=thread_context,
            project_context=project_context,
            tool_context=tool_context,
        ),
    )


def task_playbook_context(
    text: str,
    host: str = "",
    limit: int = 2,
    *,
    thread_context: str = "",
    project_context: str = "",
    tool_context: str = "",
) -> str:
    playbooks = matching_playbooks(
        text,
        host=host,
        limit=limit,
        thread_context=thread_context,
        project_context=project_context,
        tool_context=tool_context,
    )
    if not playbooks:
        return ""
    lines = [
        "KNOWN PRACTICES AND TECHNIQUES:",
        "Use these expert local DCC/engine recipes before open-ended planning. Ask only for missing slots that block safe execution.",
        "Context rule: interpret vague follow-ups against the recent thread, active project, and host/tool context before asking the user to restate the task.",
    ]
    for playbook in playbooks:
        lines.extend([
            "",
            f"Playbook: {playbook.title}",
            f"Summary: {playbook.summary}",
            "Preferred operations: " + ", ".join(playbook.prefer_operations or ("registered host operations",)),
            "Logical action path:",
        ])
        lines.extend(f"- {step}" for step in (playbook.action_path or DEFAULT_ACTION_PATH))
        lines.extend([
            "Steps:",
        ])
        lines.extend(f"- {step}" for step in playbook.steps)
        if playbook.ask_when_missing:
            lines.append("Ask when missing: " + "; ".join(playbook.ask_when_missing))
        if playbook.avoid:
            lines.append("Avoid:")
            lines.extend(f"- {item}" for item in playbook.avoid)
    return "\n".join(lines)


def best_practices_context(
    text: str,
    host: str = "",
    limit: int = 2,
    *,
    thread_context: str = "",
    project_context: str = "",
    tool_context: str = "",
    allow_research: bool = False,
) -> str:
    local_context = task_playbook_context(
        text,
        host=host,
        limit=limit,
        thread_context=thread_context,
        project_context=project_context,
        tool_context=tool_context,
    )
    assessment = assess_best_practice_coverage(
        text,
        host=host,
        limit=max(3, limit),
        thread_context=thread_context,
        project_context=project_context,
        tool_context=tool_context,
    )
    sections = [local_context] if local_context else []
    if not assessment.should_offer_research:
        return "\n\n".join(section for section in sections if section)

    if allow_research:
        sections.append(
            "\n".join(
                [
                    "OPTIONAL BEST-PRACTICE RESEARCH:",
                    f"Local guidance confidence: {assessment.confidence}.",
                    "Why research may help:",
                    *[f"- {reason}" for reason in assessment.reasons],
                    "Offer the user these choices when research would improve safety or quality: Use Existing Knowledge; Research Best Practices; Research and Build Recommended Workflow; Proceed Without Additional Research.",
                    "If the operation is destructive, hard to reverse, or version-specific, strongly recommend research before executing.",
                    "Research authority order: explicit project rules, provider capability metadata, official documentation/API contracts, verified internal workflows, static project analysis, then clearly labeled community guidance.",
                    "Evaluate results for source authority, host/API version, editor/runtime context, deprecation state, completeness, and conflicts.",
                    "Research query:",
                    assessment.research_query,
                    "Expected research report fields: Task; Provider and version; Recommended approach; Required context; Required APIs/functions; Preferred execution sequence; Safety requirements; Performance considerations; Discouraged/deprecated approaches; Alternative valid approaches; Validation steps; Sources; Confidence; Unresolved questions.",
                ]
            )
        )
    else:
        sections.append(
            "\n".join(
                [
                    "BEST-PRACTICE COVERAGE NOTE:",
                    f"Local guidance confidence: {assessment.confidence}.",
                    "Live best-practice research is disabled for this request. Use local knowledge conservatively, or offer to research authoritative best practices before planning/executing if the user wants better results.",
                    "Why research may help:",
                    *[f"- {reason}" for reason in assessment.reasons],
                    "Suggested research query if enabled:",
                    assessment.research_query,
                ]
            )
        )
    return "\n\n".join(section for section in sections if section)


def playbook_keys(playbooks: Iterable[TaskPlaybook]) -> list[str]:
    return [playbook.key for playbook in playbooks]
