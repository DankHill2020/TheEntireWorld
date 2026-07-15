# unreal_intent_parser.py
"""Rich natural-language → Unreal action intent parser.

Replaces the old keyword-chain in command_router.unreal_natural_asset_query.

Two-pass detection:
  Pass 1 – Presence of any Unreal-vocabulary signal (asset type, subsystem,
            explicit app name, or /Game/ path).  If score == 0 → None.
  Pass 2 – Presence of an action verb broad enough to cover conversational
            English.  If no action found → falls back to "query" for high
            confidence signals.

Returns an UnrealIntent dataclass or None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Asset type table
# Each entry: (aliases_tuple, canonical_class_name, human_label, signal_weight)
# signal_weight = how strongly this alias implies Unreal (1 = maybe, 2 = strong)
# ---------------------------------------------------------------------------

ASSET_TYPES: Tuple[Tuple, ...] = (
    # ── Blueprints ──────────────────────────────────────────────────────────
    (("blueprint",  "blueprints", "bp",
      "anim bp", "animation bp", "animation blueprint", "animation blueprints",
      "widget blueprint", "widget blueprints", "actor blueprint",
      "game mode blueprint", "character blueprint"),
     "Blueprint", "Blueprints", 2),

    # ── Skeletal meshes ─────────────────────────────────────────────────────
    (("skeletal mesh", "skeletal meshes", "skeletalmesh", "skel mesh",
      "skinned mesh", "character mesh"),
     "SkeletalMesh", "Skeletal Meshes", 2),

    # ── Static meshes ───────────────────────────────────────────────────────
    (("static mesh", "static meshes", "staticmesh", "prop mesh",
      "environment mesh", "sm_"),
     "StaticMesh", "Static Meshes", 1),

    # ── Animations ──────────────────────────────────────────────────────────
    (("animation sequence", "animation sequences",
      "anim sequence", "anim sequences",
      "animation asset", "animations", "animation clip",
      "anim clip", "anim asset"),
     "AnimSequence", "Animation Sequences", 2),

    # ── Skeletons ───────────────────────────────────────────────────────────
    (("skeleton", "skeletons", "rig skeleton"),
     "Skeleton", "Skeletons", 2),

    # ── Materials ───────────────────────────────────────────────────────────
    (("material", "materials", "material instance", "material instances",
      "mat instance", "matinst", "shader"),
     "Material", "Materials", 1),

    # ── Textures ────────────────────────────────────────────────────────────
    (("texture", "textures", "texture2d", "tex"),
     "Texture2D", "Textures", 1),

    # ── Level Sequences ─────────────────────────────────────────────────────
    (("level sequence", "level sequences", "cinematic", "cinematics",
      "sequencer", "cutscene"),
     "LevelSequence", "Level Sequences", 2),

    # ── Maps / Levels ───────────────────────────────────────────────────────
    (("map", "maps", "level", "levels", "world", "worlds",
      "persistent level", "sublevel"),
     "World", "Maps/Levels", 1),

    # ── Niagara ─────────────────────────────────────────────────────────────
    (("niagara", "niagra", "niagara system", "niagara systems", "niagra system",
      "niagra systems", "emitter", "emitters", "particle system",
      "particle systems", "vfx asset", "fx asset"),
     "NiagaraSystem", "Niagara Systems", 2),

    # ── Physics Assets ──────────────────────────────────────────────────────
    (("physics asset", "physics assets", "phat", "ragdoll asset"),
     "PhysicsAsset", "Physics Assets", 2),

    # ── Control Rig ─────────────────────────────────────────────────────────
    (("control rig", "control rigs", "controlrig"),
     "ControlRigBlueprint", "Control Rigs", 2),

    # ── Motion Matching ─────────────────────────────────────────────────────
    (("motion matching", "motion matching database",
      "motion matching db", "pose search"),
     "MotionMatchingDatabase", "Motion Matching Databases", 2),

    # ── IK Rig / IK Retargeter ──────────────────────────────────────────────
    (("ik rig", "ik rigs", "ikrig",
      "ik retargeter", "ik retargeters", "retarget"),
     "IKRig", "IK Rigs", 2),

    # ── Sound ───────────────────────────────────────────────────────────────
    (("sound cue", "sound cues", "sound wave", "sound waves",
      "audio asset", "sound asset"),
     "SoundCue", "Sound Assets", 1),

    # ── Data Assets / Data Tables ────────────────────────────────────────────
    (("data asset", "data assets", "data table", "data tables",
      "datatable", "row struct"),
     "DataAsset", "Data Assets", 1),

    # ── Meta Sounds ─────────────────────────────────────────────────────────
    (("metasound", "metasounds", "meta sound"),
     "MetaSoundSource", "MetaSounds", 2),
)

# Flat alias → (class_name, label, weight) for fast lookup
_ALIAS_MAP: dict[str, tuple[str, str, int]] = {}
for _aliases, _cls, _lbl, _wt in ASSET_TYPES:
    for _a in _aliases:
        _ALIAS_MAP[_a] = (_cls, _lbl, _wt)


# ---------------------------------------------------------------------------
# Unreal-specific subsystem / concept signals (weight 2 each = hard Unreal)
# ---------------------------------------------------------------------------

UNREAL_CONCEPT_SIGNALS: tuple[str, ...] = (
    "unreal", "ue5", "ue4", "uproject", "uasset", "umap",
    "/game/", "content browser", "unreal editor",
    "blueprint", "control rig", "niagara", "niagra", "emitter", "emitters",
    "motion matching", "animation blueprint", "sequencer", "ik rig",
    "gameplay ability", "gas ", "gameplay ability system",
    "metasound", "chaos", "nanite", "lumen",
    "world partition", "open world",
    "actor component", "game mode", "player controller",
    "game instance", "subsystem",
    "ufunction", "uproperty", "uclass",
)

# ---------------------------------------------------------------------------
# Action verbs — extremely broad to cover conversational English
# ---------------------------------------------------------------------------

ACTION_VERBS: dict[str, str] = {
    # ── high-specificity multi-word phrases first ─────────────────────────
    "pull up":      "list",
    "give me":      "list",
    "what are":     "list",
    "what is":      "list",
    "tell me":      "list",
    "look up":      "list",
    "look at":      "inspect",
    "do i have":    "list",
    "are there":    "list",
    "map out":      "scan",
    "set up":       "create",
    "what blueprints": "list",
    "what assets":  "list",
    "what materials": "list",
    "what meshes":  "list",
    # ── scan / snapshot / debug / compile / create (before generic verbs) ─
    "scan":         "scan",
    "snapshot":     "snapshot",
    "index":        "scan",
    "analyze":      "scan",
    "analyse":      "scan",
    "audit":        "scan",
    "debug":        "debug",
    "fix":          "debug",
    "broken":       "debug",
    "errors":       "debug",
    "warnings":     "debug",
    "diagnose":     "debug",
    "repair":       "debug",
    "compile":      "compile",
    "recompile":    "compile",
    "rebuild":      "compile",
    "create":       "create",
    "make":         "create",
    "build":        "create",
    "generate":     "create",
    "prototype":    "create",
    "implement":    "create",
    "new":          "create",
    "setup":        "create",
    "add":          "create",
    "connect":      "create",
    "attach":       "create",
    "link":         "create",
    "wire":         "create",
    "bind":         "create",
    # ── inspect ───────────────────────────────────────────────────────────
    "inspect":      "inspect",
    "open":         "inspect",
    "view":         "inspect",
    "examine":      "inspect",
    "check":        "inspect",
    "details":      "inspect",
    "info":         "inspect",
    # ── generic inventory / query (lowest priority) ───────────────────────
    "list":         "list",
    "show":         "list",
    "find":         "list",
    "get":          "list",
    "fetch":        "list",
    "grab":         "list",
    "display":      "list",
    "lookup":       "list",
    "search":       "list",
    "enumerate":    "list",
    "print":        "list",
    "dump":         "list",
    "which":        "list",
}

# ---------------------------------------------------------------------------
# Guidance / purely educational patterns — block dispatch when matched
_GUIDANCE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bhow (?:do|can|should|would) (?:i|you|we)\b", re.I),
    re.compile(r"\bwhat (?:is|are) (?:the )?(?:best|proper|correct|right) way\b", re.I),
    re.compile(r"\bexplain\b", re.I),
    re.compile(r"\btutorial\b", re.I),
    re.compile(r"\bwalk me through\b", re.I),
    re.compile(r"\bcan you (?:explain|teach|tell me about)\b", re.I),
    re.compile(r"\bwhat does .+ (?:do|mean)\b", re.I),
    # "tell me about X" WITHOUT a path or inventory verb → guidance
    re.compile(r"\btell me (?:about|what) (?:a |an |the )?(?!the ik|the control|the motion|the niagara)", re.I),
)

# A guidance match overrides dispatch UNLESS the confidence score is ≥ this
_GUIDANCE_OVERRIDE_THRESHOLD = 6

# Regex to match /Game/ paths in the prompt
_PATH_RE = re.compile(r"(/Game/[A-Za-z0-9_/.-]*)", re.I)


def _alias_matches_text(alias: str, text: str) -> bool:
    """Match Unreal aliases without letting short words fire inside project terms."""
    if not alias:
        return False
    if re.search(r"\W", alias):
        return alias in text
    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])", text))


# ---------------------------------------------------------------------------
# Intent dataclass
# ---------------------------------------------------------------------------

@dataclass
class UnrealIntent:
    action:      str              # "list" | "inspect" | "scan" | "snapshot" | "debug" | "create" | "compile"
    asset_class: str              # e.g. "Blueprint", "SkeletalMesh", or "" for project-wide
    label:       str              # human-readable label for UI
    directory:   str = "/Game/"  # target content-browser path
    confidence:  int = 0          # 0–10 score used to gate dispatch


def parse(text: str) -> Optional[UnrealIntent]:
    """Parse *text* and return an UnrealIntent if confident enough, else None."""
    if not text:
        return None

    q = text.lower()

    # ── Pass 1: accumulate Unreal signal score ───────────────────────────
    score = 0

    # Explicit "unreal" mention (very strong signal)
    if any(sig in q for sig in ("unreal", "ue5", "ue4", "uproject", "uasset", "umap")):
        score += 3

    # Any other Unreal-specific concept
    for sig in UNREAL_CONCEPT_SIGNALS:
        if sig in q:
            score += 2
            break  # one point per concept bucket

    # /Game/ path → definitive Unreal
    if _PATH_RE.search(text):
        score += 3

    # Asset-type alias match (adds weight from the table)
    matched_class = ""
    matched_label = ""
    matched_weight = 0
    for alias, (cls, lbl, wt) in _ALIAS_MAP.items():
        if _alias_matches_text(alias, q):
            if wt > matched_weight:
                matched_class = cls
                matched_label = lbl
                matched_weight = wt
            score += wt

    # ── If no signal at all → bail immediately ───────────────────────────
    if score == 0:
        return None

    # ── Guidance check ────────────────────────────────────────────────────
    is_guidance = any(p.search(text) for p in _GUIDANCE_PATTERNS)
    if is_guidance and score < _GUIDANCE_OVERRIDE_THRESHOLD:
        return None

    # ── Pass 2: find action verb ──────────────────────────────────────────
    detected_action = ""
    for verb, action in ACTION_VERBS.items():
        if verb in q:
            detected_action = action
            break  # first match wins; table is ordered by priority

    # No verb + low confidence → not worth dispatching
    if not detected_action and score < 4:
        return None

    # Fallback action for high-confidence but verb-less queries
    if not detected_action:
        detected_action = "list"

    # ── Extract /Game/ path if present ───────────────────────────────────
    m = _PATH_RE.search(text)
    directory = m.group(1) if m else "/Game/"

    # ── Build label ───────────────────────────────────────────────────────
    if matched_label:
        label = f"Unreal {matched_label}"
    else:
        label = {
            "list":     "Unreal Asset Query",
            "inspect":  "Unreal Asset Inspect",
            "scan":     "Unreal Project Scan",
            "snapshot": "Unreal Snapshot",
            "debug":    "Unreal Debug",
            "create":   "Unreal Create",
            "compile":  "Unreal Compile",
        }.get(detected_action, "Unreal Operation")

    # Cap confidence at 10
    confidence = min(score, 10)

    return UnrealIntent(
        action=detected_action,
        asset_class=matched_class,
        label=label,
        directory=directory,
        confidence=confidence,
    )


def to_command_router_result(
    intent: UnrealIntent,
) -> Optional[tuple[str, str, list, dict]]:
    """Convert an UnrealIntent into the 4-tuple expected by command_router:
    (label, function_path, args, kwargs)

    Returns None for actions that should be handled by a dedicated
    main_window method rather than a generic asset query.
    """
    if intent.action in ("scan", "snapshot", "debug", "compile"):
        # Caller should route to direct_unreal_project_scan / snapshot / debug_from_text
        return None

    if intent.action == "list" and intent.asset_class:
        return (
            intent.label,
            "unreal_tools.get_skeletons.get_all_assets_of_type",
            [intent.asset_class, intent.directory],
            {},
        )

    if intent.action == "inspect" and intent.asset_class:
        return (
            intent.label,
            "unreal_tools.asset_inspector.inspect_assets_of_type",
            [intent.asset_class, intent.directory],
            {},
        )

    # Generic list-all-assets fallback
    if intent.action == "list":
        return (
            "Unreal Asset Query",
            "unreal_tools.get_skeletons.get_all_assets_of_type",
            ["Blueprint", intent.directory],
            {},
        )

    return None


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        # Should fire even without "unreal"
        "show me my blueprints",
        "list all skeletal meshes",
        "what control rigs do I have?",
        "find my niagara systems",
        "get all animation sequences under /Game/Characters/",
        # Should fire with "unreal"
        "what assets do I have in unreal?",
        "unreal: list all materials in /Game/Materials/",
        "scan unreal project for broken blueprints",
        # Should NOT fire
        "how do I create a blueprint in unreal?",
        "explain what a control rig is",
        "can you teach me about motion matching?",
        # Borderline — should fire (high confidence concept + action)
        "pull up all motion matching databases",
        "tell me about the ik rigs in the project",
    ]
    print(f"{'Input':<60} {'Action':<10} {'Class':<25} {'Conf'}")
    print("-" * 110)
    for t in tests:
        intent = parse(t)
        if intent:
            print(f"{t:<60} {intent.action:<10} {intent.asset_class or '(all)':<25} {intent.confidence}")
        else:
            print(f"{t:<60} {'SKIPPED':<10}")
