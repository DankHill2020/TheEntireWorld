"""Engineering reasoning engine for Tech Connector.

Detects complex engineering prompts and produces structured reasoning:
  - Understanding (goal, success criteria, constraints, unknowns)
  - Investigation queries (what to ask the DCC before executing)
  - Possible solutions with pros/cons/risk
  - Execution steps
  - Verification checklist
  - Potential risks

This runs BEFORE code generation so the user sees a staff-level technical
lead thinking through the problem rather than immediately reaching for a
keyboard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SolutionOption:
    name: str
    description: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    risk: str = "low"  # "low" | "medium" | "high" | "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "pros": self.pros,
            "cons": self.cons,
            "risk": self.risk,
        }


@dataclass
class EngineeringReasoning:
    domain: str
    prompt: str

    # Understanding
    goal: str = ""
    success_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)

    # Investigation (filled before or after live DCC query)
    investigation_queries: list[str] = field(default_factory=list)
    files_inspected: list[str] = field(default_factory=list)
    existing_implementations: list[str] = field(default_factory=list)
    architecture_notes: list[str] = field(default_factory=list)

    # Solutions
    options: list[SolutionOption] = field(default_factory=list)
    recommended_option: str = ""

    # Execution
    execution_steps: list[str] = field(default_factory=list)

    # Verification
    verification_steps: list[str] = field(default_factory=list)

    # Risks
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "prompt": self.prompt,
            "goal": self.goal,
            "success_criteria": self.success_criteria,
            "constraints": self.constraints,
            "unknowns": self.unknowns,
            "investigation_queries": self.investigation_queries,
            "files_inspected": self.files_inspected,
            "existing_implementations": self.existing_implementations,
            "architecture_notes": self.architecture_notes,
            "options": [o.to_dict() for o in self.options],
            "recommended_option": self.recommended_option,
            "execution_steps": self.execution_steps,
            "verification_steps": self.verification_steps,
            "risks": self.risks,
        }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_ENGINEERING_TRIGGERS = (
    # Refactor / architecture
    "refactor", "duplicate", "duplicat", "common parent", "reusable",
    "inherit", "inheritance", "extract", "migrate", "migration",
    "consolidat", "decouple", "modular", "shared component", "shared logic",
    # Analysis / audit
    "analyze", "analyse", "audit", "inspect", "scan", "find every",
    "search for", "find all", "identify", "detect", "review",
    "performance", "optimiz", "optimi", "profil", "budget", "expensive",
    "draw call", "triangle", "polygon", "vertex", "shader", "nanite",
    "hlod", "lod", "texture stream", "virtual shadow", "blueprint tick",
    # System building
    "build a", "create a system", "implement", "design", "architect",
    "combat system", "health system", "inventory", "ability system",
    "gas", "gameplay ability", "gameplay tag", "third-person", "third person",
    "multiplayer", "replication", "networked", "save system",
    # Validation / fixing
    "validate", "validat", "verify", "broken reference", "missing reference",
    "fix redirect", "naming convention", "deprecated", "unused asset",
    "circular reference", "dependency graph",
    # Complex multi-step
    "for every", "for each", "all blueprint", "all material", "all asset",
    "every blueprint", "every material", "every asset",
)

_SIMPLE_TRIGGERS = (
    "rename", "move to", "set ", "change color", "change name",
    "add a", "create a new", "open ", "select ", "delete ",
)


def is_senior_engineering_prompt(prompt: str) -> bool:
    """Return True if the prompt warrants structured engineering reasoning.

    Fires on complex, multi-step, architectural, refactor, analysis, or
    system-building requests. Does not fire for simple single-step mutations.
    """
    q = (prompt or "").lower().strip()
    if not q or len(q) < 20:
        return False

    engineering_score = sum(1 for t in _ENGINEERING_TRIGGERS if t in q)
    if engineering_score == 0:
        return False

    # Suppress for trivially simple prompts even if they hit one trigger
    simple_score = sum(1 for t in _SIMPLE_TRIGGERS if q.startswith(t))
    if simple_score >= 2 and engineering_score == 1:
        return False

    # Multi-verb prompts are almost always complex
    action_verbs = ("create", "find", "scan", "move", "fix", "compile", "save",
                    "verify", "generate", "analyze", "inspect", "build", "add",
                    "rename", "update", "replace", "compile", "report", "attach")
    verb_count = sum(1 for v in action_verbs if re.search(rf"\b{v}\b", q))
    if verb_count >= 3:
        return True

    return engineering_score >= 1


# ---------------------------------------------------------------------------
# Prompt parsing helpers
# ---------------------------------------------------------------------------

def _extract_goal(prompt: str) -> str:
    """Extract a concise goal statement from the prompt."""
    q = prompt.strip()
    # Strip leading filler
    q = re.sub(r"^(please|can you|i want you to|i need you to|i'd like you to)\s+", "", q, flags=re.I)
    # Truncate at the first comma, period, or "and then" if too long
    short = re.split(r",\s*(?:then|and|next|after)", q)[0].strip()
    if len(short) > 120:
        short = short[:117] + "..."
    return short[0].upper() + short[1:] if short else q[:120]


def _extract_asset_paths(prompt: str) -> list[str]:
    return re.findall(r"/Game/[A-Za-z0-9/_.-]+", prompt)


def _detect_asset_types(prompt: str) -> list[str]:
    q = prompt.lower()
    types = []
    mapping = {
        "blueprint": "Blueprint",
        "static mesh": "StaticMesh",
        "skeletal mesh": "SkeletalMesh",
        "material": "Material",
        "texture": "Texture",
        "niagara": "NiagaraSystem",
        "animation blueprint": "AnimBlueprint",
        "animation sequence": "AnimSequence",
        "level sequence": "LevelSequence",
        "physics asset": "PhysicsAsset",
        "control rig": "ControlRig",
        "data asset": "DataAsset",
        "data table": "DataTable",
        "actor": "Actor",
        "component": "Component",
    }
    for keyword, cls in mapping.items():
        if keyword in q:
            types.append(cls)
    return list(dict.fromkeys(types))  # dedupe preserving order


def _detect_domain_subsystem(prompt: str) -> str:
    """Detect the primary Unreal subsystem targeted by the prompt."""
    q = prompt.lower()
    if any(k in q for k in ("niagara", "particle", "emitter", "vfx")):
        return "niagara"
    if any(k in q for k in ("sequencer", "level sequence", "cinematic", "camera cut")):
        return "sequencer"
    if any(k in q for k in ("animation blueprint", "anim bp", "state machine", "aim offset", "locomotion")):
        return "animation"
    if any(k in q for k in ("blueprint", "bp_", "actor blueprint", "component blueprint")):
        return "blueprint"
    if any(k in q for k in ("material", "texture", "shader")):
        return "material"
    if any(k in q for k in ("level", "world", "map", "lighting", "player start", "sky atmosphere")):
        return "level"
    if any(k in q for k in ("skeletal mesh", "physics asset", "control rig")):
        return "skeletal"
    if any(k in q for k in ("performance", "draw call", "nanite", "lod", "hlod", "profil")):
        return "performance"
    if any(k in q for k in ("refactor", "migrate", "duplicate logic", "naming convention", "deprecated")):
        return "refactoring"
    if any(k in q for k in ("asset", "content browser", "redirect", "unused")):
        return "asset_management"
    return "general"


# ---------------------------------------------------------------------------
# Solution option templates
# ---------------------------------------------------------------------------

def _options_for_refactor_duplicate() -> list[SolutionOption]:
    return [
        SolutionOption(
            name="Option A",
            description="Reuse an existing common parent (if already found)",
            pros=["Zero new assets", "Lowest migration effort"],
            cons=["Depends on finding a suitable parent in the scan"],
            risk="low",
        ),
        SolutionOption(
            name="Option B",
            description="Create a reusable Blueprint Component to hold shared logic",
            pros=["Preserves existing inheritance", "Composable — attach to any Blueprint", "Easy rollback"],
            cons=["Slight increase in component overhead"],
            risk="low",
        ),
        SolutionOption(
            name="Option C",
            description="Create a new parent class and reparent all affected Blueprints",
            pros=["Clean inheritance hierarchy", "Shared logic in one place"],
            cons=["Reparenting requires careful testing", "Breaks if children already have custom parents"],
            risk="medium",
        ),
        SolutionOption(
            name="Option D",
            description="Leave behavior as-is (if differences are intentional)",
            pros=["No risk", "No migration"],
            cons=["Duplication persists"],
            risk="none",
        ),
    ]


def _options_for_build_system(prompt: str) -> list[SolutionOption]:
    q = prompt.lower()
    uses_gas = any(k in q for k in ("gas", "gameplay ability", "ability system component"))
    return [
        SolutionOption(
            name="Option A",
            description="Extend or compose existing components already in the project",
            pros=["Fastest path", "Fits current architecture", "Minimal new assets"],
            cons=["May be constrained by existing design decisions"],
            risk="low",
        ),
        SolutionOption(
            name="Option B",
            description="Create a new standalone Blueprint subsystem",
            pros=["Clean separation of concerns", "Easier to test in isolation"],
            cons=["More assets to maintain", "Integration work required"],
            risk="medium",
        ),
        SolutionOption(
            name="Option C",
            description="Implement using Unreal's Gameplay Ability System (GAS)" if uses_gas else "Implement using engine-native framework (GAS / Enhanced Input / etc.)",
            pros=["Battle-tested", "Replication-ready out of the box", "Scalable"],
            cons=["Higher learning curve", "Requires GAS plugin enabled", "More upfront setup"],
            risk="medium",
        ),
    ]


def _options_for_analysis() -> list[SolutionOption]:
    return [
        SolutionOption(
            name="Option A",
            description="Report only — surface all findings as Critical / Warning / Suggestion without modifying anything",
            pros=["Zero risk", "Full visibility before any change"],
            cons=["No automatic remediation"],
            risk="none",
        ),
        SolutionOption(
            name="Option B",
            description="Auto-fix safe issues + flag manual review items",
            pros=["Immediate improvement on safe issues", "Annotated report for manual items"],
            cons=["Some fixes may have unexpected side effects"],
            risk="low",
        ),
        SolutionOption(
            name="Option C",
            description="Auto-fix all detected issues",
            pros=["Maximum automation"],
            cons=["Higher risk — some fixes may affect gameplay or rendering"],
            risk="medium",
        ),
    ]


def _options_for_optimization() -> list[SolutionOption]:
    return [
        SolutionOption(
            name="Option A",
            description="Enable Nanite on high-polygon static meshes",
            pros=["Dramatic triangle-count reduction", "GPU-driven culling"],
            cons=["Not compatible with all materials or translucency"],
            risk="low",
        ),
        SolutionOption(
            name="Option B",
            description="Generate LODs for meshes lacking them",
            pros=["Reduces GPU load at distance", "Non-destructive"],
            cons=["Requires tuning per mesh for quality"],
            risk="low",
        ),
        SolutionOption(
            name="Option C",
            description="Add cull distance volumes to large scenes",
            pros=["Actor-level culling without modifying meshes"],
            cons=["Requires placement and tuning"],
            risk="low",
        ),
        SolutionOption(
            name="Option D",
            description="Merge static mesh instances using ISMC/HISM",
            pros=["Drastically reduces draw calls for repeated meshes"],
            cons=["Removes ability to move individual instances at runtime"],
            risk="medium",
        ),
    ]


def _options_for_asset_management() -> list[SolutionOption]:
    return [
        SolutionOption(
            name="Option A",
            description="Scan, report, then apply changes with confirmation",
            pros=["Full visibility before mutation", "Safest"],
            cons=["Requires extra step"],
            risk="low",
        ),
        SolutionOption(
            name="Option B",
            description="Apply changes automatically, fix redirectors, save all",
            pros=["Fastest path to clean state"],
            cons=["Irreversible without source control"],
            risk="medium",
        ),
    ]


def _generate_solution_options(prompt: str, subsystem: str) -> tuple[list[SolutionOption], str]:
    """Return (options, recommended_option_name) for the given prompt."""
    q = prompt.lower()

    if any(k in q for k in ("duplicate", "common parent", "refactor", "inherit", "reusable", "shared logic", "shared functionality", "migrate")):
        opts = _options_for_refactor_duplicate()
        return opts, "Option B"

    if any(k in q for k in ("build a", "create a system", "implement", "combat system", "health system", "inventory", "ability", "gameplay")):
        opts = _options_for_build_system(prompt)
        return opts, "Option A"

    if any(k in q for k in ("performance", "draw call", "nanite", "lod", "hlod", "profil", "expensive", "budget", "triangle")):
        opts = _options_for_optimization()
        return opts, "Option A"

    if any(k in q for k in ("analyze", "analyse", "audit", "inspect", "scan for", "find every", "find all")):
        opts = _options_for_analysis()
        return opts, "Option B"

    if subsystem == "asset_management" or any(k in q for k in ("unused", "redirect", "naming convention", "deprecated")):
        opts = _options_for_asset_management()
        return opts, "Option A"

    # Fallback: simple 2-option choice
    return [
        SolutionOption(
            name="Option A",
            description="Inspect first, then execute with confirmation",
            pros=["Safe", "Full context before mutation"],
            cons=["Requires extra round-trip"],
            risk="low",
        ),
        SolutionOption(
            name="Option B",
            description="Execute directly based on resolved context",
            pros=["Faster"],
            cons=["Less visibility"],
            risk="low",
        ),
    ], "Option A"


# ---------------------------------------------------------------------------
# Investigation query generation
# ---------------------------------------------------------------------------

def _build_investigation_queries(prompt: str, asset_paths: list[str], asset_types: list[str], subsystem: str) -> list[str]:
    queries = []
    q = prompt.lower()

    for path in asset_paths:
        for atype in asset_types or ["Asset"]:
            queries.append(f"Scan {path} for all {atype} assets")

    if subsystem == "blueprint" or "blueprint" in q:
        queries.append("Inspect inheritance hierarchy of all found Blueprints")
        queries.append("Check for implemented interfaces on each Blueprint")
        queries.append("Identify duplicated graphs, variables, and functions across Blueprints")
        if "interaction" in q or "button" in q or "door" in q:
            queries.append("Look for existing overlap events and interaction functions")
    if subsystem == "animation" or "animation" in q:
        queries.append("Check if an Animation Blueprint already exists for the target skeletal mesh")
        queries.append("List available animation sequences compatible with the target skeleton")
    if subsystem == "niagara" or "niagara" in q:
        queries.append("Inspect existing Niagara Systems for deprecated modules")
        queries.append("Check parameter interfaces and emitter counts")
    if subsystem == "performance" or "performance" in q:
        queries.extend([
            "Count draw calls per frame in current level",
            "Identify static meshes with no LODs or Nanite enabled",
            "List Blueprint Actors with active Tick enabled at high frequency",
            "Identify shadow-casting actors with high triangle counts",
            "Check Niagara Systems for particle budget overruns",
            "Find lights without baked shadow maps or virtual shadow maps",
        ])
    if subsystem == "refactoring" or "refactor" in q:
        queries.append("Search project for deprecated Blueprint API nodes")
        queries.append("Generate asset dependency graph for the target path")
    if subsystem == "asset_management":
        queries.append("Scan for assets with no referencing actors, Blueprints, or Data Assets")
        queries.append("Find assets violating naming conventions")

    if not queries:
        if asset_paths:
            queries.append(f"Scan {asset_paths[0]} for relevant assets")
        else:
            queries.append("Inspect active Unreal project context")

    return queries


# ---------------------------------------------------------------------------
# Execution step generation
# ---------------------------------------------------------------------------

def _build_execution_steps(prompt: str, options: list[SolutionOption], recommended: str) -> list[str]:
    q = prompt.lower()

    if any(k in q for k in ("duplicate", "common parent", "refactor", "shared logic", "shared functionality")):
        return [
            "Inspect all target Blueprints and document shared logic",
            "Create reusable Blueprint Component or parent class",
            "Move shared variables into the new component/class",
            "Move shared functions into the new component/class",
            "Reconnect events and references in each Blueprint",
            "Compile all modified Blueprints (expect zero errors)",
            "Save all modified assets",
            "Verify functionality in PIE and report results",
        ]

    if any(k in q for k in ("combat system", "health system", "inventory", "build a")):
        return [
            "Inventory existing relevant components and classes",
            "Determine integration points with chosen solution option",
            "Create new Blueprint or C++ class for the system",
            "Implement core variables and exposed properties",
            "Wire events, delegates, and replication settings",
            "Attach to or extend relevant Actor/Pawn/Character classes",
            "Compile all modified Blueprints",
            "Playtest in PIE to verify all paths",
            "Save and document",
        ]

    if any(k in q for k in ("performance", "analyze", "optimiz", "audit")):
        return [
            "Run complete project analysis scan",
            "Categorize findings as Critical / Warning / Suggestion",
            "Apply safe automatic fixes (LOD generation, Nanite enable, Tick disable)",
            "Flag issues requiring manual review",
            "Re-run analysis scan to confirm improvements",
            "Generate before/after comparison report",
        ]

    if any(k in q for k in ("find every", "find all", "scan", "search for", "for every", "for each")):
        return [
            "Scan target folder/project for matching assets",
            "Validate findings against criteria",
            "Apply changes to qualifying assets",
            "Fix redirectors",
            "Save all modified assets",
            "Verify no broken references remain",
            "Generate report",
        ]

    # Fallback: derive from prompt sub-steps
    raw_steps = []
    parts = re.split(r"\b(?:then|and|afterwards|next|after that)\b|,\s*(?=\w)", prompt)
    for part in parts:
        p = part.strip().strip(".!?,")
        if p and len(p) > 8 and not any(w in p.lower() for w in ("i want you", "please", "make sure")):
            raw_steps.append(p[0].upper() + p[1:])
    if raw_steps:
        return raw_steps[:10]

    return ["Inspect and resolve context", "Execute operation", "Compile and save", "Verify and report"]


# ---------------------------------------------------------------------------
# Verification steps
# ---------------------------------------------------------------------------

def _build_verification_steps(prompt: str, subsystem: str) -> list[str]:
    q = prompt.lower()
    steps = []

    if "blueprint" in q or subsystem == "blueprint":
        steps.append("Compile all modified Blueprints — zero errors, zero warnings required")
    if any(k in q for k in ("level", "world", "map")):
        steps.append("Open level in editor and verify all actors are correctly placed")
    if "animation" in q or subsystem == "animation":
        steps.append("Preview animation state machine transitions in Animation Blueprint editor")
        steps.append("Test locomotion in PIE")
    if "niagara" in q or subsystem == "niagara":
        steps.append("Compile each Niagara System — check for module errors")
        steps.append("Spawn system in level and verify visual output")
    if "sequencer" in q or subsystem == "sequencer":
        steps.append("Play Level Sequence in editor — verify all camera cuts and bindings")
    if any(k in q for k in ("performance", "draw call", "lod", "nanite")):
        steps.append("Open GPU Visualizer (Shift+2) and compare draw calls before/after")
        steps.append("Check Stat GPU, Stat SceneRendering in PIE")
    if any(k in q for k in ("refactor", "migrate", "reparent")):
        steps.append("Run full project compile — confirm zero Blueprint errors project-wide")
        steps.append("Regression test: verify original gameplay behavior is unchanged")

    if not steps:
        steps.append("Verify expected assets/actors exist in Content Browser / Level")
        steps.append("Check Output Log for errors after execution")

    steps.append("Check Content Browser for broken references (Right-click → Fix Up Redirectors)")
    return steps


# ---------------------------------------------------------------------------
# Risk generation
# ---------------------------------------------------------------------------

def _build_risks(prompt: str, options: list[SolutionOption], recommended: str) -> list[str]:
    q = prompt.lower()
    risks = []

    if any(k in q for k in ("refactor", "migrate", "reparent", "inherit")):
        risks.append("Breaking: Existing event node bindings may require manual rewiring after reparenting")
        risks.append("Edge case: Blueprints that already have a non-Actor custom parent may not be compatible")
        risks.append("Rollback: Create a Git commit or make a content folder backup before migration begins")

    if any(k in q for k in ("rename", "move", "redirect", "naming convention")):
        risks.append("Breaking: All assets referencing moved/renamed assets will require reference updates")
        risks.append("Rollback: Fix-up redirectors can be reversed via source control")

    if any(k in q for k in ("delete", "remove", "unused", "archive")):
        risks.append("Caution: 'Unused' detection cannot catch soft references in config files or Data Tables — verify before deletion")
        risks.append("Rollback: Move to Archive folder instead of permanent deletion until verified")

    if any(k in q for k in ("compile", "blueprint", "variable")):
        risks.append("Edge case: Blueprint nodes referencing renamed/moved variables will show as errors until manually reconnected")

    if any(k in q for k in ("replication", "multiplayer", "networked")):
        risks.append("Warning: Replication changes require testing in a multi-client PIE session, not standalone")

    if any(k in q for k in ("nanite", "lod", "material")):
        risks.append("Caution: Nanite is incompatible with masked materials, two-sided foliage, and pixel depth offset")
        risks.append("Verification: Always check for rendering artifacts in lit viewport after enabling Nanite")

    if not risks:
        risks.append("Low risk — changes are reversible via source control")
        risks.append("Verify: Run full project compile after execution to catch any cascading reference issues")

    return risks


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def analyze_prompt(prompt: str, domain: str = "unreal") -> EngineeringReasoning:
    """Parse a complex engineering prompt into a full EngineeringReasoning object.

    This is the primary entry point. Call this before dispatching a complex
    prompt to any DCC. The returned object is then rendered as a reasoning
    card in the chat UI.
    """
    q = (prompt or "").strip()
    subsystem = _detect_domain_subsystem(q)
    asset_paths = _extract_asset_paths(q)
    asset_types = _detect_asset_types(q)

    goal = _extract_goal(q)

    # Success criteria
    success_criteria = []
    if "compile" in q.lower():
        success_criteria.append("Zero compile errors or warnings")
    if any(k in q.lower() for k in ("save", "saved")):
        success_criteria.append("All modified assets saved to disk")
    if any(k in q.lower() for k in ("verify", "verif", "report")):
        success_criteria.append("Verification report generated")
    if any(k in q.lower() for k in ("no broken", "no reference", "fix redirect")):
        success_criteria.append("No broken asset references remaining")
    if not success_criteria:
        success_criteria.append("Operation completes without errors")
        success_criteria.append("Expected assets/changes visible in editor")

    # Constraints
    constraints = []
    if any(k in q.lower() for k in ("do not break", "preserve", "without breaking", "keep existing")):
        constraints.append("Preserve existing Blueprint/actor behavior")
    if any(k in q.lower() for k in ("do not delete", "instead of deleting", "archive")):
        constraints.append("Do not permanently delete — archive instead")
    if any(k in q.lower() for k in ("game", "gameplay")):
        constraints.append("Do not change gameplay behavior")
    if not constraints:
        constraints.append("Avoid breaking existing references or gameplay")

    # Unknowns
    unknowns = []
    if any(k in q.lower() for k in ("if so", "if one exists", "if available", "if found", "if no")):
        unknowns.append("Whether a suitable existing implementation exists (requires live scan)")
    if any(k in q.lower() for k in ("refactor", "duplicate")):
        unknowns.append("Whether differences in behavior are intentional or accidental duplication")
    if "performance" in q.lower():
        unknowns.append("Current draw call / triangle / GPU budget baseline (requires live session)")
    if any(k in q.lower() for k in ("selected", "selection")):
        unknowns.append("Which actors / assets are currently selected in the editor")
    if not unknowns:
        unknowns.append("Full project context — investigation will clarify before execution")

    investigation_queries = _build_investigation_queries(q, asset_paths, asset_types, subsystem)
    options, recommended = _generate_solution_options(q, subsystem)
    execution_steps = _build_execution_steps(q, options, recommended)
    verification_steps = _build_verification_steps(q, subsystem)
    risks = _build_risks(q, options, recommended)

    return EngineeringReasoning(
        domain=domain,
        prompt=q,
        goal=goal,
        success_criteria=success_criteria,
        constraints=constraints,
        unknowns=unknowns,
        investigation_queries=investigation_queries,
        options=options,
        recommended_option=recommended,
        execution_steps=execution_steps,
        verification_steps=verification_steps,
        risks=risks,
    )


def enrich_with_investigation(reasoning: EngineeringReasoning, investigation_result: dict[str, Any]) -> EngineeringReasoning:
    """Fill in live DCC investigation data into an existing EngineeringReasoning.

    Call this after getting results back from the live Unreal/DCC bridge.
    The investigation_result dict may contain keys like:
      - "assets_found": list of asset paths found
      - "blueprints": list of Blueprint paths
      - "existing_components": list of component names found
      - "parent_classes": dict of bp_path -> parent_class
      - "architecture_notes": list of strings
    """
    from copy import deepcopy
    r = deepcopy(reasoning)

    assets_found = list(investigation_result.get("assets_found") or [])
    blueprints = list(investigation_result.get("blueprints") or [])
    existing = list(investigation_result.get("existing_components") or [])
    arch_notes = list(investigation_result.get("architecture_notes") or [])

    r.files_inspected = assets_found + blueprints
    r.existing_implementations = existing
    r.architecture_notes = arch_notes

    # If a reusable parent/component was found, promote Option A
    if existing or investigation_result.get("common_parent"):
        r.recommended_option = "Option A"

    return r


# ---------------------------------------------------------------------------
# Senior Prompt Analysis Ported Functions
# ---------------------------------------------------------------------------


"""Senior-level prompt interpretation for routing and execution planning.

This layer is deliberately deterministic. It does not replace route selection;
it enriches each route with the investigation contract a senior coding system
should honor before editing, executing, or asking the user for clarification.
"""

import re
from typing import Any


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text or "", re.IGNORECASE))


def _unique(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        item = str(item or "").strip()
        if item and item not in out:
            out.append(item)
    return out


def _symbols(text: str) -> list[str]:
    found = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\b", text or "")
    stop = {
        "add", "allow", "and", "before", "but", "can", "code", "determine",
        "design", "do", "does", "existing", "feature", "find", "first", "for",
        "function", "identify", "implementation", "in", "is", "it", "make",
        "module", "new", "operation", "project", "refactor", "request", "should",
        "system", "that", "the", "this", "through", "to", "without", "work",
    }
    return _unique([item for item in found if item.lower() not in stop and len(item) > 2])[:12]


def _objective(prompt: str) -> str:
    text = re.sub(r"\s+", " ", prompt or "").strip()
    return text[:220] if text else "Understand and route the user request."


def analyze_senior_prompt(
    prompt: str,
    *,
    route: str = "",
    intent_category: str = "",
    host: str = "",
    provider: str = "",
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lower = (prompt or "").lower()
    category = intent_category or "general"
    affected: list[str] = []
    required_context: list[str] = []
    unknowns: list[str] = []
    investigation_steps: list[str] = []
    deterministic_tools: list[str] = []
    deliverables: list[str] = []
    verification: list[str] = []
    fallback: list[str] = []
    risks: list[str] = []
    alternatives: list[str] = []
    disqualifying: list[str] = []

    if host:
        affected.append(host)
    if _has(r"\b(ui|widget|dialog|panel|tab|chat|window)\b", lower):
        affected.append("ui")
    if _has(r"\b(router|routing|prompt|intent|dispatch|handler)\b", lower):
        affected.append("prompt_routing")
    if _has(r"\b(index|search|symbol|dependency|call graph|project search)\b", lower):
        affected.append("project_index")
    if _has(r"\b(pipeline|workflow|node graph|graph)\b", lower):
        affected.append("workflow_pipeline")
    if _has(r"\b(plugin|registry|capability pack|third-party|external module)\b", lower):
        affected.append("plugin_registry")
    if _has(r"\b(maya|unreal|motionbuilder|blender|unity|substance)\b", lower):
        affected.append("dcc_bridge")
    if _has(r"\b(config|settings|serialized|persistence|database|db)\b", lower):
        affected.append("persistence")
    if not affected and route in {"target_discovery", "quality_audit", "project_search"}:
        affected.append("project_code")

    wants_change = _has(r"\b(add|implement|change|modify|refactor|replace|fix|clean up|cleanup|make|improve|create|support)\b", lower)
    wants_runtime = _has(r"\b(run|execute|call|launch|open|compile|spawn|create asset|in unreal|in maya|in blender)\b", lower)
    vague_quality = _has(r"\b(make|improve|clean up|production ready|scalable|maintainable|fragile|better)\b", lower) and not _has(
        r"\b(latency|ranking|recall|memory|startup|specific|line|file|function|class|method|error|traceback)\b",
        lower,
    )
    root_cause = _has(r"\b(root cause|actual behavioral difference|fails when|works when|only occurs|stale|outdated|wrong conversation|called but|same operation twice|different results)\b", lower)
    architecture = _has(r"\b(architecture|abstraction|extension point|plugin system|interface|canonical|backward compatibility|compatibility|adapter|subsystem)\b", lower)
    async_state = _has(r"\b(async|asynchronous|concurrent|cancellation|stale result|queue|retry|double-click|callback|destroyed|transactional|undo|redo|crash|resume)\b", lower)
    security = _has(r"\b(security|permission|credential|audit trail|remote|trust|confirmation|destructive|injection|validate generated commands)\b", lower)
    testing = _has(r"\b(test|tests|regression|contract|verify|verification|adversarial|coverage)\b", lower)
    observability = _has(r"\b(logging|metrics|correlation|trace|diagnose|diagnostic|progress|machine-readable|logs)\b", lower)

    if architecture:
        category = category if category not in {"general_chat", ""} else "architecture_design"
        required_context.extend(["existing implementations", "extension points", "callers", "registries", "configuration"])
        investigation_steps.extend([
            "Search for existing equivalent capabilities before proposing new code.",
            "Identify active runtime entrypoints, registries, handlers, and serialized references.",
            "Separate verified facts from architecture recommendations.",
        ])
        deterministic_tools.extend(["project index", "symbol lookup", "reference search", "targeted file inspection"])
        risks.extend(["Breaking existing callers or saved data", "Adding a parallel implementation instead of extending the canonical path"])
    if root_cause:
        category = "root_cause_investigation"
        investigation_steps.extend([
            "Trace the direct path and failing path from trigger through result handling.",
            "Compare inputs, state, threading, routing, and error propagation between paths.",
            "Create or identify a minimal reproduction before fixing.",
        ])
        deterministic_tools.extend(["call graph", "usage search", "structured logs", "targeted file inspection"])
        verification.extend(["Regression test or smoke path demonstrating the failing path now matches the direct path."])
        risks.extend(["Fixing a symptom while the real divergence remains in another layer"])
    if async_state:
        category = "async_state_consistency"
        required_context.extend(["operation lifecycle", "thread ownership", "cancellation boundaries", "state persistence"])
        investigation_steps.extend([
            "Identify request IDs, worker lifetime, callback ownership, and stale-result overwrite paths.",
            "Find partial-success and retry boundaries before introducing new concurrency.",
        ])
        deterministic_tools.extend(["event/callback search", "state owner inspection", "lifecycle tests"])
        risks.extend(["Old responses overwriting newer state", "Partial external mutations without rollback"])
    if security:
        category = "security_trust_boundary"
        required_context.extend(["permission model", "confirmation policy", "credential storage", "audit logging"])
        investigation_steps.extend([
            "Classify read-only, mutation, execution, and destructive operations.",
            "Locate trust boundaries between user input, project content, plugins, and DCC command execution.",
        ])
        deterministic_tools.extend(["configuration scan", "command validation inspection", "audit log inspection"])
        risks.extend(["Prompt injection through indexed content", "Credential or command leakage"])
    if testing:
        required_context.extend(["unit seams", "integration seams", "host bridge availability", "serialized fixtures"])
        verification.extend([
            "Add focused unit tests for deterministic logic.",
            "Add regression coverage that verifies behavior without overfitting implementation details.",
        ])
    if observability:
        required_context.extend(["routing events", "execution events", "diagnostic logs", "user-facing progress"])
        deliverables.append("Structured progress and diagnostic events with enough context to reconstruct failures.")

    if route in {"target_discovery", "quality_audit", "project_search", "project_health"}:
        required_context.extend(["project index", "symbol index", "relevant files"])
        deterministic_tools.extend(["project search", "symbol lookup"])
        investigation_steps.append("Use indexed candidates, then verify top candidates by reading actual files.")
    if route in {"dcc_execute", "dcc_query", "dcc_prototype", "unreal_capability"} or host:
        required_context.extend(["DCC connection state", "registered operation metadata", "argument schema"])
        deterministic_tools.extend(["operation registry", "bridge health check", "argument validation"])
        if wants_runtime:
            verification.append("Report exact DCC operation, affected assets/objects, validation result, and recovery action.")
    if wants_change:
        deliverables.extend(["Grounded change summary", "Before/after impact", "QA steps"])
        verification.append("Run the narrowest relevant syntax/unit/smoke validation available.")
    if vague_quality:
        unknowns.extend(["Which quality dimension matters most: correctness, UX, ranking, latency, maintainability, reliability, or scale"])
        investigation_steps.append("Decompose the vague improvement into measurable failure modes before editing.")
        disqualifying.append("Do not assume a generic refactor is desired without evidence of the failing dimension.")
    if "project search" in lower and "better" in lower:
        alternatives.extend(["ranking", "recall", "latency", "symbol understanding", "stale index handling", "result presentation"])
    if not unknowns and _has(r"\b(this|that|it|feature|system|operation)\b", lower) and not _symbols(prompt):
        unknowns.append("The concrete target may need to be inferred from active file, recent thread context, or a clarifying question.")

    fallback.extend([
        "Ask only for missing information that cannot be inferred from project context.",
        "If deterministic evidence is insufficient, stop at an investigation report instead of inventing an implementation.",
    ])
    if route in {"target_discovery", "dcc_execute", "dcc_prototype", "unreal_capability"}:
        fallback.append("Require confirmation before mutating files, saved workflows, or external DCC state.")

    existing = existing or {}
    required_context.extend(existing.get("required_context") or [])
    deterministic_tools.extend(existing.get("context_resolvers") or [])
    investigation_steps.extend(existing.get("deterministic_steps") or [])
    unknowns.extend(existing.get("missing_info") or [])
    disqualifying.extend(existing.get("disqualifiers") or [])

    return {
        "primary_objective": _objective(prompt),
        "intent_category": category,
        "affected_subsystems": _unique(affected),
        "required_context": _unique(required_context),
        "known_entities": _symbols(prompt),
        "unknown_or_ambiguous": _unique(unknowns),
        "investigation_steps": _unique(investigation_steps),
        "deterministic_tools_required": _unique(deterministic_tools),
        "code_modification_required": bool(wants_change or route in {"target_discovery", "pipeline_graph", "action_graph"}),
        "runtime_execution_required": bool(wants_runtime or route in {"dcc_execute", "dcc_query", "dcc_prototype", "unreal_capability"}),
        "potentially_destructive_actions": _unique(["file mutation"] if wants_change else []),
        "confirmation_requirements": _unique(["confirm before mutation"] if existing.get("requires_confirmation") else []),
        "expected_deliverables": _unique(deliverables or ["Investigation summary", "Recommended next action"]),
        "verification_criteria": _unique(verification or ["Verify with deterministic evidence or explain why validation is unavailable."]),
        "fallback_and_recovery": _unique(fallback),
        "likely_architectural_risks": _unique(risks),
        "alternative_interpretations": _unique(alternatives),
        "disqualifying_assumptions": _unique(disqualifying),
    }


def render_senior_prompt_analysis(analysis: dict[str, Any] | None, *, max_items: int = 4) -> str:
    if not analysis:
        return ""
    lines = [
        "Prompt understanding:",
        f"Objective: {analysis.get('primary_objective', '')}",
        f"Intent: {analysis.get('intent_category', '')}",
    ]
    for label, key in (
        ("Affected", "affected_subsystems"),
        ("Needs", "required_context"),
        ("Unknowns", "unknown_or_ambiguous"),
        ("Investigate", "investigation_steps"),
        ("Verify", "verification_criteria"),
    ):
        values = list(analysis.get(key) or [])[:max_items]
        if values:
            lines.append(f"{label}: " + "; ".join(str(v) for v in values))
    return "\n".join(lines)
