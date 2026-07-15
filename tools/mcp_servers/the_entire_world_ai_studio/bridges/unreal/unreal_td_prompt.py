# unreal_td_prompt.py
"""
Unreal Technical Director system prompt builder.

Assembles three layers dynamically for every Unreal-context LLM call:

  Layer 1 – TD Persona      : Who the model is and its engineering priorities.
  Layer 2 – Project Context : Live state from UnrealScanner + .project_ai/ rules.
  Layer 3 – Exec Philosophy : Capability-first, compose-before-create directive.

Usage
-----
    from project_analysis.unreal_td_prompt import build_unreal_system_prompt
    system = build_unreal_system_prompt(scanner_summary=..., capabilities=..., rules=...)
    # prepend `system` to the LLM context window
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional


# ============================================================================
# SNAPSHOT PARSING HELPERS
# ============================================================================

def parse_unreal_snapshot(raw: str) -> Dict[str, Any]:
    """Parse the raw JSON blob produced by direct_unreal_project_snapshot.

    Returns a clean dict:
      connected  : bool
      level      : str | None          # loaded level name
      assets     : Dict[class, list]   # class → [asset names]
      warnings   : List[str]
      error      : str | None          # set when bridge is unreachable
    """
    result: Dict[str, Any] = {
        "connected": False,
        "level": None,
        "assets": {},
        "warnings": [],
        "error": None,
    }
    if not raw:
        return result

    # Strip markdown fences if present
    cleaned = raw.strip()
    for fence in ("```json", "```", "```python"):
        if cleaned.startswith(fence):
            cleaned = cleaned[len(fence):]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except Exception:
        # Not JSON — treat as a plain error string
        result["error"] = cleaned[:300]
        return result

    if "stages" in data or "data" in data:
        scan_data = data.get("data") if isinstance(data.get("data"), dict) else data
        if not isinstance(scan_data, dict):
            scan_data = {}
        health = scan_data.get("health") if isinstance(scan_data, dict) else {}
        if not isinstance(health, dict):
            health = {}
        result["connected"] = bool(data.get("connected") or health.get("connected"))
        result["level"] = scan_data.get("loaded_level") or health.get("loaded_level")
        result["warnings"] += data.get("warnings", [])
        if data.get("cache_used"):
            result["warnings"].append(
                "Unreal live bridge unavailable. Using cached project intelligence from "
                f"{data.get('scanned_at') or scan_data.get('scanned_at') or 'unknown time'}."
            )
        if not result["connected"] and not data.get("cache_used"):
            result["error"] = (health or {}).get("error") or "Unreal HTTP bridge not reachable."
        assets: Dict[str, List[str]] = {}
        for key, cls in [
            ("blueprints", "Blueprint"),
            ("skeletal_meshes", "SkeletalMesh"),
            ("animations", "AnimSequence"),
            ("available_tools", "EditorUtilityBlueprint"),
            ("selected_assets", "SelectedAsset"),
            ("selected_actors", "SelectedActor"),
        ]:
            values = scan_data.get(key) or data.get(key) or []
            if isinstance(values, list) and values:
                assets[cls] = [str(v) for v in values]
        counts = scan_data.get("asset_counts") or data.get("asset_counts") or {}
        if isinstance(counts, dict):
            for cls, count in counts.items():
                if cls not in assets and count:
                    assets[str(cls)] = [f"{count} asset(s) counted"]
        result["assets"] = assets
        if assets:
            result["error"] = None
        return result

    # ── Level ──────────────────────────────────────────────────────────────
    level_entry = data.get("level", {})
    if isinstance(level_entry, dict):
        ok = level_entry.get("ok", False)
        level_result = level_entry.get("result", "")

        # Unpack nested JSON in result field (common pattern from the HTTP bridge)
        if isinstance(level_result, str) and level_result.strip().startswith("{"):
            try:
                level_result = json.loads(level_result)
            except Exception:
                pass

        if ok:
            result["connected"] = True
            name = level_result if isinstance(level_result, str) else level_result.get("level", "Unknown")
            result["level"] = name
        else:
            # Distinguish hard bridge failure from missing endpoint module
            err_str = str(level_result).lower()
            is_bridge_down = (
                "bridge not found" in err_str
                or "connection refused" in err_str
                or "port 12347" in err_str
                or ("not found on port" in err_str and "http" in err_str)
            )
            if is_bridge_down:
                # Only bail if NO asset entries have returned ok yet
                # (assets are parsed next; wait to see if bridge is truly down)
                result["error"] = "Unreal HTTP bridge not reachable — start the Unreal project first."
                # Don't return yet — let asset parsing determine if bridge is up
            else:
                # Module missing / endpoint not installed — bridge IS alive
                result["warnings"].append(
                    f"Level endpoint unavailable: {str(level_result)[:120]}"
                )
    elif isinstance(level_entry, str):
        result["level"] = level_entry
        result["connected"] = True

    # ── Asset classes ───────────────────────────────────────────────────────
    # Real snapshot format from the Unreal HTTP bridge:
    #   {"asset_class": "Skeleton", "ok": true, "result": "{\"SK_Mannequin\": {\"class\": \"SK_Mannequin\", ...}, ...}"}
    # The result value is a JSON *object* whose *keys* are asset names.
    for entry in data.get("assets", []):
        cls        = entry.get("asset_class", "Unknown")
        ok         = entry.get("ok", False)
        raw_result = entry.get("result", "")
        if not ok:
            continue

        result["connected"] = True
        result["error"] = None  # bridge is alive even if level module was missing

        names: List[str] = []
        try:
            parsed = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
            if isinstance(parsed, dict):
                if "assets" in parsed:
                    # {'assets': ['name1', 'name2', ...]}
                    names = [str(n) for n in parsed["assets"]]
                else:
                    # {'AssetName': {'class': ..., 'class_name': ...}, ...}  ← real format
                    names = [k for k in parsed.keys() if not k.startswith("_")]
            elif isinstance(parsed, list):
                names = [str(n) for n in parsed]
        except Exception:
            # Last resort: plain string
            names = [n.strip() for n in str(raw_result).replace("\n", ",").split(",") if n.strip()]

        if names:  # skip empty classes (PoseSearchDatabase={}, etc.)
            result["assets"][cls] = names

    result["warnings"] += data.get("warnings", [])
    return result


def _asset_index_path(project_root: Optional[str] = None) -> pathlib.Path:
    root = pathlib.Path(project_root) if project_root else pathlib.Path.cwd()
    return root / ".project_ai" / "asset_index.json"


def load_cached_asset_index(project_root: Optional[str] = None) -> Dict[str, Any]:
    """Load the last-known good asset index from .project_ai/asset_index.json."""
    path = _asset_index_path(project_root)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_asset_index(parsed: Dict[str, Any], project_root: Optional[str] = None) -> None:
    """Write parsed asset data back to .project_ai/asset_index.json."""
    if not parsed.get("connected"):
        return
    path = _asset_index_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        out = {
            "level":     parsed.get("level"),
            "assets":    parsed.get("assets", {}),
            "warnings":  parsed.get("warnings", []),
        }
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    except Exception:
        pass


def _format_asset_section(
    assets: Dict[str, List[str]],
    level: Optional[str],
    source_tag: str,
) -> List[str]:
    """Render the asset counts + sampled names into prompt lines."""
    lines: List[str] = []
    if level:
        lines.append(f"Loaded Level: {level}")
    lines.append(f"\nProject Assets ({source_tag}):")
    total = 0
    for cls, names in sorted(assets.items()):
        count = len(names)
        total += count
        sample = ", ".join(names[:6])
        suffix = f"  … +{count-6} more" if count > 6 else ""
        lines.append(f"  {cls:<32} {count:>4} asset(s)   {sample}{suffix}")
    if total == 0:
        lines.append("  (no assets indexed yet)")
    return lines


# ============================================================================
# LAYER 1 — STATIC TD PERSONA  (never changes per-session)
# ============================================================================

_TD_PERSONA = """\
You are a Senior Principal Unreal Engine Technical Director, Gameplay Engineer, \
and Pipeline Engineer with deep specialisation in Unreal Engine 5.

Your responsibility is NOT simply to write code.
Your responsibility is to DESIGN maintainable, production-ready gameplay systems, \
editor tooling, animation pipelines, asset workflows, and cross-DCC pipelines \
that integrate cleanly into an existing, evolving Unreal project.

Assume you are embedded inside a large professional game production with multiple \
engineers, technical artists, animators, and designers. Every decision you make \
will affect their work for the next five years.

═══════════════════════════════════════════════════════
 PRIORITIES  (in strict order)
═══════════════════════════════════════════════════════
1. Understand the existing project before making ANY change.
2. Reuse existing systems whenever possible.
3. Extend existing functionality — never duplicate it.
4. Produce modular, maintainable, scalable solutions.
5. Follow Unreal Engine best practices and Epic coding standards.
6. Minimise technical debt.
7. Explain every architectural decision and WHY it was chosen over alternatives.

═══════════════════════════════════════════════════════
 MANDATORY PRE-WORK BEFORE GENERATING ANYTHING
═══════════════════════════════════════════════════════
Before writing a single line of code or Blueprint:
  • Analyse the project structure provided in context.
  • Identify existing assets, classes, Blueprints, plugins, and registered tools.
  • Search for reusable functionality — ask: "Does something already solve part of this?"
  • Determine dependencies and potential circular references.
  • Produce an implementation plan.
  • Only then generate code.

Always prefer COMPOSITION over REPLACEMENT.

═══════════════════════════════════════════════════════
 BLUEPRINT STANDARDS
═══════════════════════════════════════════════════════
• Prefer Blueprint Function Libraries for reusable logic.
• Avoid Event Tick — use event-driven patterns.
• Minimise Blueprint spaghetti — encapsulate into Functions and Macros.
• Keep graphs readable; a designer must be able to maintain this in six months.
• Document nodes with comments.
• Consider future engineers and technical artists who will maintain the graph.

═══════════════════════════════════════════════════════
 C++ STANDARDS
═══════════════════════════════════════════════════════
• Follow Epic's Unreal C++ coding standard.
• Minimise unnecessary UObject allocations.
• Use appropriate UPROPERTY / UFUNCTION reflection macros.
• Avoid unnecessary Blueprint exposure — only expose what designers need.
• Respect memory ownership and GC implications.
• Always consider networking (replication, authority, prediction).
• Consider editor performance — tools should not stall the editor.

═══════════════════════════════════════════════════════
 ANIMATION SYSTEMS
═══════════════════════════════════════════════════════
Always evaluate which Unreal system is most appropriate before building:
  • Animation Blueprints (ABP) + State Machines
  • Linked Anim Layers (LAL) for modular animation
  • Motion Matching + Pose Search
  • Control Rig (procedural + authored rigs)
  • IK Rig + IK Retargeter (cross-skeleton retargeting)
  • Animation Notifies + Notify States
  • Root Motion vs in-place with character movement
  • Gameplay Tags for animation state filtering
  • Network replication of animation state

Never build animation systems in isolation when Unreal already provides the capability.

═══════════════════════════════════════════════════════
 ASSET MANAGEMENT
═══════════════════════════════════════════════════════
Before creating any asset, determine:
  • Existing references and redirectors
  • Naming conventions (project-specific; see context below)
  • Folder organisation and content hierarchy
  • Hard vs soft references and load implications
  • Circular reference risks
  • Dependency chains

Avoid creating duplicate assets. Search first.

═══════════════════════════════════════════════════════
 CHOOSING IMPLEMENTATION ARCHITECTURE
═══════════════════════════════════════════════════════
When creating new functionality, first determine the correct container:

  Blueprint              — designer-editable logic, rapid prototyping
  C++                    — performance-critical, networked, engine-integrated
  Editor Utility Widget  — editor tooling with UI
  Editor Utility Blueprint — editor scripting without UI
  Python (unreal module) — batch pipeline automation, asset operations
  Plugin                 — reusable cross-project systems
  Modular Gameplay Feature — isolated, toggleable gameplay module
  Data Asset             — configuration / balance data
  Data Table             — tabular design data
  Gameplay Ability (GAS) — ability system actions
  Component              — composable actor behaviour
  Subsystem              — global singleton service (Game, Engine, Editor, World)

Choose the MOST MAINTAINABLE architecture, not the fastest to implement.

═══════════════════════════════════════════════════════
 GENERAL ENGINEERING PRINCIPLES
═══════════════════════════════════════════════════════
• Build reusable, generalised systems — not one-off solutions.
• Build editor automation wherever manual steps are repeated.
• Think like a Technical Director responsible for the next five years.
• Optimise for long-term maintainability over short-term velocity.
"""


# ============================================================================
# LAYER 2 — DYNAMIC PROJECT CONTEXT  (assembled at query time)
# ============================================================================

def _build_project_context(
    scanner_summary: str = "",
    rules: Dict[str, Any] = None,
    capabilities: List[Dict[str, Any]] = None,
    git_branch: str = "",
    engine_version: str = "",
    project_root: Optional[str] = None,
    raw_snapshot: str = "",
) -> str:
    rules = rules or {}
    capabilities = capabilities or []

    lines = [
        "═══════════════════════════════════════════════════════",
        " CURRENT PROJECT CONTEXT  (live, auto-injected)",
        "═══════════════════════════════════════════════════════",
    ]

    # Engine version
    ev = engine_version or rules.get("engine_version", "")
    if ev:
        lines.append(f"Engine Version: {ev}")

    # Git branch (auto-detect if not supplied)
    if not git_branch:
        try:
            import subprocess
            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=2,
            )
            git_branch = r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            git_branch = ""
    if git_branch:
        lines.append(f"Git Branch: {git_branch}")

    # ── Studio rules ────────────────────────────────────────────────────
    if "rules" in rules:
        lines += ["", "Studio Rules:", str(rules["rules"])[:1200]]

    # ── Model routing ───────────────────────────────────────────────────
    if "model_routing" in rules:
        mr = rules["model_routing"]
        lines.append("\nModel Routing Preferences:")
        if isinstance(mr, dict):
            for tier, model in mr.items():
                lines.append(f"  {tier}: {model}")

    # ── Asset / level state ─────────────────────────────────────────────
    # Priority 1: parse the raw live snapshot (from direct_unreal_project_snapshot)
    snap: Dict[str, Any] = {}
    if raw_snapshot:
        snap = parse_unreal_snapshot(raw_snapshot)
        if snap.get("connected"):
            save_asset_index(snap, project_root)  # update cache while live

    if snap.get("connected") and snap.get("assets"):
        # ✅ Live Unreal connection — show real data
        lines += [""] + _format_asset_section(
            snap["assets"], snap.get("level"), source_tag="live"
        )
        if snap.get("warnings"):
            for w in snap["warnings"][:3]:
                lines.append(f"  ⚠ {w}")

    elif snap.get("error"):
        # ❌ Bridge unreachable — try cache
        cache = load_cached_asset_index(project_root)
        if cache.get("assets"):
            lines += [
                "",
                f"⚠ Unreal not reachable ({snap['error']})",
                "Showing last-known project state (cached):",
            ] + _format_asset_section(
                cache["assets"], cache.get("level"), source_tag="cached"
            )
        else:
            lines += [
                "",
                "⚠ Unreal not running — no cached asset index available.",
                "Start your Unreal project and run Tools → Unreal → Project Snapshot",
                "to populate live project context.",
            ]

    elif scanner_summary:
        # Fallback: plain-text scanner summary (from UnrealScanner.build_context_summary)
        lines += ["", scanner_summary[:4000]]

    # ── Reusable DCC local intelligence context ─────────────────────────────
    # This augments the older asset summary with selected state, relevant assets,
    # capabilities, dependency edges, and recent execution history from SQLite.
    try:
        from bridges.unreal.unreal_intelligence import build_context as _build_local_context
    except Exception:
        try:
            from unreal_intelligence import build_context as _build_local_context
        except Exception:
            _build_local_context = None

    if _build_local_context:
        try:
            local_context = _build_local_context("unreal project context", project_root=project_root)
            if local_context:
                lines += ["", local_context[:6000]]
        except Exception:
            pass

    # ── Available internal tools ─────────────────────────────────────────
    if capabilities:
        lines += ["", "Available Internal Tools (registered capabilities):"]
        for cap in capabilities[:30]:
            name = cap.get("name", "")
            app  = cap.get("app", "")
            risk = cap.get("risk", "")
            doc  = (cap.get("docstring") or "")[:80].replace("\n", " ")
            lines.append(f"  • {name}  [{app}] [risk:{risk}]  {doc}")
        if len(capabilities) > 30:
            lines.append(f"  … and {len(capabilities)-30} more.")

    return "\n".join(lines)


# ============================================================================
# LAYER 3 — EXECUTION PHILOSOPHY  (static, inserted after context)
# ============================================================================

_EXEC_PHILOSOPHY = """\
═══════════════════════════════════════════════════════
 EXECUTION PHILOSOPHY  (mandatory, always follow)
═══════════════════════════════════════════════════════
You are NOT a code assistant. You are an autonomous Unreal development partner.

Before generating any new code, ALWAYS determine whether the requested
functionality can be accomplished by:
  1. Existing project code or Blueprints listed in the project context above.
  2. Existing registered internal tools (listed above).
  3. Native Unreal Engine systems.
  4. Installed plugins already in the project.
  5. Optional external resources from GitHub (only if the user has enabled
     "Allow GitHub/tool search" in the Model & Safety panel).

If any of the above partially satisfy the requirement — INTEGRATE with those
systems rather than recreating them.

When functionality is genuinely missing, follow this sequence:
  Step 1: Search the project (assets, Blueprints, C++ classes, Python tools).
  Step 2: Search registered capabilities in the capability registry.
  Step 3: Search optional GitHub resources (if "Allow GitHub/tool search" is on).
  Step 4: Compose existing tools into a new workflow wherever possible.
  Step 5: Generate ONLY the missing functionality — no duplicates.
  Step 6: Register any newly created capability so it can be reused in future
           workflows. This expands the project's permanent capability graph.

Treat every completed task as an opportunity to improve the project's long-term
capability surface rather than merely solving the immediate request.

NEVER blindly generate boilerplate. NEVER duplicate existing systems.
ALWAYS explain your architectural reasoning before writing code.
ALWAYS produce an implementation plan before executing it.
"""


# ============================================================================
# PUBLIC API
# ============================================================================

def build_unreal_system_prompt(
    scanner_summary: str = "",
    rules: Optional[Dict[str, Any]] = None,
    capabilities: Optional[List[Dict[str, Any]]] = None,
    git_branch: str = "",
    engine_version: str = "",
    include_philosophy: bool = True,
    project_root: Optional[str] = None,
    raw_snapshot: str = "",
) -> str:
    """Assemble the full three-layer Unreal TD system prompt.

    Parameters
    ----------
    scanner_summary   : Output of UnrealScanner.build_context_summary() (plain text)
    raw_snapshot      : Raw JSON string from direct_unreal_project_snapshot (preferred)
    rules             : Loaded .project_ai/ rules dict from rules_loader.load_rules()
    capabilities      : List of capability dicts from capability_registry
    git_branch        : Current VCS branch (auto-detected if empty)
    engine_version    : UE version string (read from .uproject if empty)
    project_root      : Project root for cache reads/writes
    include_philosophy: Whether to append the execution philosophy section
    """
    parts = [_TD_PERSONA]

    context = _build_project_context(
        scanner_summary=scanner_summary,
        rules=rules or {},
        capabilities=capabilities or [],
        git_branch=git_branch,
        engine_version=engine_version,
        project_root=project_root,
        raw_snapshot=raw_snapshot,
    )
    parts.append(context)

    if include_philosophy:
        parts.append(_EXEC_PHILOSOPHY)

    return "\n\n".join(parts)


def build_for_prompt(
    text: str,
    project_root: Optional[str] = None,
    scanner=None,
    cap_query: str = "",
    raw_snapshot: str = "",
) -> str:
    """Convenience wrapper: auto-loads rules + capabilities + snapshot.

    Parameters
    ----------
    text         : The user's prompt (used to pick relevant capabilities)
    project_root : Path to the project root (for rules_loader + asset cache)
    scanner      : Optional UnrealScanner instance
    cap_query    : Override capability search query
    raw_snapshot : Raw JSON string from direct_unreal_project_snapshot
    """
    # Load .project_ai/ rules
    rules: Dict[str, Any] = {}
    try:
        from project_analysis.rules_loader import load_rules
        rules = load_rules(project_root)
    except Exception:
        try:
            from bridges.unreal.rules_loader import load_rules  # alternate location
            rules = load_rules(project_root)
        except Exception:
            pass

    # Load capabilities relevant to this query
    caps: List[Dict[str, Any]] = []
    try:
        from project_analysis.capability_registry import find_capabilities
        query = cap_query or (text[:60] if text else "unreal")
        caps = find_capabilities(query, max_results=25)
        unreal_caps = find_capabilities("", app="Unreal", max_results=15)
        seen = {c["name"] for c in caps}
        caps += [c for c in unreal_caps if c["name"] not in seen]
    except Exception:
        pass

    # Scanner plain-text summary (fallback if no raw_snapshot)
    summary = ""
    if scanner is not None and not raw_snapshot:
        try:
            summary = scanner.build_context_summary()
        except Exception:
            pass

    # Auto-detect engine version from .uproject
    engine_version = ""
    try:
        import pathlib
        root = pathlib.Path(project_root) if project_root else pathlib.Path.cwd()
        for uproject in list(root.glob("*.uproject"))[:1]:
            data = json.loads(uproject.read_text(encoding="utf-8"))
            engine_version = data.get("EngineAssociation", "")
            break
    except Exception:
        pass

    return build_unreal_system_prompt(
        scanner_summary=summary,
        raw_snapshot=raw_snapshot,
        rules=rules,
        capabilities=caps,
        engine_version=engine_version,
        project_root=project_root,
    )
