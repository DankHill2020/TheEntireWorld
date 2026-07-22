"""Semantic contracts for selecting gameplay animation assets.

Import compatibility is necessary but not sufficient: a clip can target the
right skeleton and still be the wrong motion.  These contracts let prompt
plans reject semantically unrelated online results before they reach Unreal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


@dataclass(frozen=True)
class AnimationRoleContract:
    role: str
    required_terms: tuple[str, ...]
    supporting_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    loop_expected: bool | None
    root_motion_policy: str
    expected_posture: str
    min_semantic_score: int = 5
    min_required_hits: int = 1
    min_supporting_hits: int = 0


ROLE_CONTRACTS: dict[str, AnimationRoleContract] = {
    "climb_loop": AnimationRoleContract(
        "climb_loop",
        ("climb",),
        ("wall", "ladder", "vertical", "loop", "hang"),
        ("dance", "samba", "attack", "roll", "vault"),
        True,
        "in_place_preferred",
        "vertical wall-facing locomotion",
        min_supporting_hits=1,
    ),
    "climb_hang": AnimationRoleContract(
        "climb_hang",
        ("hang",),
        ("ledge", "climb", "wall", "idle"),
        ("dance", "attack", "run"),
        True,
        "in_place_required",
        "suspended ledge hold",
        min_supporting_hits=1,
    ),
    "climb_wall_jump": AnimationRoleContract(
        "climb_wall_jump",
        ("jump",),
        ("wall", "climb", "back", "rebound", "leap"),
        ("dance", "attack", "idle"),
        False,
        "root_motion_optional",
        "push away from a vertical surface",
        min_supporting_hits=1,
    ),
    "grapple_zip": AnimationRoleContract(
        "grapple_zip",
        ("grapple", "zip"),
        ("air", "swing", "hang", "travel", "rope"),
        ("dance", "attack", "roll", "walk"),
        False,
        "in_place_preferred",
        "airborne forward travel",
        min_supporting_hits=1,
    ),
    "vault": AnimationRoleContract(
        "vault",
        ("vault",),
        ("parkour", "obstacle", "mantle", "jump", "low"),
        ("dance", "attack", "roll", "climb loop"),
        False,
        "root_motion_preferred",
        "hands/legs clear a waist-high obstacle",
        min_supporting_hits=1,
    ),
    "slide": AnimationRoleContract(
        "slide",
        ("slide",),
        ("ground", "run", "sprint", "crouch", "parkour"),
        ("dance", "attack", "climb", "ice"),
        False,
        "root_motion_optional",
        "low forward ground traversal",
        min_supporting_hits=1,
    ),
    "dodge_roll": AnimationRoleContract(
        "dodge_roll",
        ("dodge", "roll", "evade"),
        ("combat", "forward", "backward", "left", "right"),
        ("dance", "attack", "climb", "vault"),
        False,
        "root_motion_optional",
        "fast directional evasive roll",
        min_supporting_hits=1,
    ),
    "ledge_shimmy": AnimationRoleContract(
        "ledge_shimmy",
        ("shimmy",),
        ("ledge", "hang", "left", "right", "side"),
        ("dance", "walk", "run", "ladder"),
        True,
        "in_place_preferred",
        "suspended lateral ledge traversal",
        min_supporting_hits=1,
    ),
    "ledge_corner": AnimationRoleContract(
        "ledge_corner",
        ("corner",),
        ("ledge", "hang", "outside", "shimmy", "turn"),
        ("dance", "ground", "walk", "run"),
        False,
        "root_motion_preferred",
        "suspended transfer around an outside ledge corner",
        min_supporting_hits=2,
    ),
    "ledge_back_jump": AnimationRoleContract(
        "ledge_back_jump",
        ("jump",),
        ("ledge", "hang", "back", "backward", "transfer"),
        ("dance", "running jump", "attack"),
        False,
        "root_motion_preferred",
        "push backward from one ledge and acquire another",
        min_supporting_hits=2,
    ),
    "prone_transition": AnimationRoleContract(
        "prone_transition",
        ("prone",),
        ("enter", "stand", "down", "up", "transition"),
        ("dance", "crawl loop", "attack"),
        False,
        "in_place_preferred",
        "controlled standing-to-prone or prone-to-standing transition",
        min_supporting_hits=1,
    ),
    "prone_crawl": AnimationRoleContract(
        "prone_crawl",
        ("crawl",),
        ("prone", "forward", "backward", "low", "loop"),
        ("dance", "hands and knees", "standing"),
        True,
        "in_place_preferred",
        "belly-down low locomotion",
        min_supporting_hits=1,
    ),
    "prone_turn": AnimationRoleContract(
        "prone_turn",
        ("prone", "turn"),
        ("180", "rotate", "crawl", "ground"),
        ("dance", "standing", "roll attack"),
        False,
        "root_motion_optional",
        "belly-down heading reversal",
        min_required_hits=2,
        min_supporting_hits=1,
    ),
    "paired_disarm_attacker": AnimationRoleContract(
        "paired_disarm_attacker",
        ("disarm",),
        ("attacker", "paired", "takedown", "weapon", "combat"),
        ("solo", "dance", "idle"),
        False,
        "root_motion_required",
        "attacker side of a synchronized weapon disarm",
        min_supporting_hits=2,
    ),
    "paired_disarm_victim": AnimationRoleContract(
        "paired_disarm_victim",
        ("disarm",),
        ("victim", "paired", "takedown", "weapon", "reaction"),
        ("solo", "dance", "idle"),
        False,
        "root_motion_required",
        "victim side of a synchronized weapon disarm",
        min_supporting_hits=2,
    ),
}


ROLE_ALIASES = {
    "vault_slide": ("vault", "slide"),
    "wall_jump": ("climb_wall_jump",),
    "ledge_hang": ("climb_hang",),
}


def animation_role_contracts(role: str) -> list[dict[str, Any]]:
    """Return every semantic contract that can satisfy a requested role."""

    normalized = re.sub(r"[^a-z0-9]+", "_", str(role or "").lower()).strip("_")
    keys = ROLE_ALIASES.get(normalized, (normalized,))
    return [asdict(ROLE_CONTRACTS[key]) for key in keys if key in ROLE_CONTRACTS]


def infer_animation_roles(text: str) -> list[str]:
    """Infer known gameplay roles from a prompt or search query."""

    lower = str(text or "").lower()
    matches: list[str] = []
    phrases = {
        "climb_loop": ("climb loop", "wall climb", "climbing"),
        "climb_hang": ("ledge hang", "climb hang", "hanging", "enters a hang", "enter a hang", "hang from"),
        "climb_wall_jump": ("wall jump", "jump from wall"),
        "grapple_zip": ("grapple", "grappling", "zipline", "zip line"),
        "vault": ("vault", "mantle"),
        "slide": ("ground slide", "combat slide", "parkour slide"),
        "dodge_roll": ("dodge", "combat roll", "evade"),
        "ledge_shimmy": ("ledge shimmy", "shimmy left", "shimmy right", "shimmies", "shimmying"),
        "ledge_corner": ("outside corner", "ledge corner", "corner shimmy"),
        "ledge_back_jump": ("backward jump", "jump backward", "jumps backward", "back jump to another ledge"),
        "prone_transition": ("enter prone", "entering prone", "stand from prone", "returning to standing", "prone transition"),
        "prone_crawl": ("prone crawl", "crawl backward", "crawling backward", "crawl forward", "crawling under"),
        "prone_turn": ("prone 180", "turning 180", "prone turn", "turn while prone", "turning while prone"),
        "paired_disarm_attacker": ("attacker disarm", "paired disarm", "disarm takedown"),
        "paired_disarm_victim": ("victim disarm", "paired disarm", "disarm takedown"),
    }
    for role, markers in phrases.items():
        if any(marker in lower for marker in markers):
            matches.append(role)
    return matches


def evaluate_animation_candidate(
    role: str,
    candidate: dict[str, Any],
    *,
    probe_only: bool = False,
) -> dict[str, Any]:
    """Score one candidate against gameplay meaning, not file compatibility."""

    contracts = animation_role_contracts(role)
    if probe_only:
        return {
            "accepted": True,
            "probe_only": True,
            "score": 0,
            "role": role,
            "reason": "Transport/import probe; not approved for gameplay-role substitution.",
            "contracts": contracts,
        }
    if not contracts:
        return {
            "accepted": False,
            "probe_only": False,
            "score": 0,
            "role": role,
            "reason": "No documented semantic contract exists for this animation role.",
            "contracts": [],
        }

    haystack = " ".join(
        str(candidate.get(key) or "")
        for key in ("name", "title", "description", "tags", "keywords", "path", "requested", "url", "download_url")
    ).lower()
    alternatives = []
    for contract in contracts:
        required_hits = [term for term in contract["required_terms"] if term in haystack]
        support_hits = [term for term in contract["supporting_terms"] if term in haystack]
        excluded_hits = [term for term in contract["excluded_terms"] if term in haystack]
        score = len(required_hits) * 5 + len(support_hits) * 2 - len(excluded_hits) * 8
        accepted = bool(
            len(required_hits) >= int(contract.get("min_required_hits") or 1)
            and len(support_hits) >= int(contract.get("min_supporting_hits") or 0)
            and not excluded_hits
            and score >= int(contract["min_semantic_score"])
        )
        alternatives.append(
            {
                "contract_role": contract["role"],
                "accepted": accepted,
                "score": score,
                "required_hits": required_hits,
                "supporting_hits": support_hits,
                "excluded_hits": excluded_hits,
            }
        )
    best = max(alternatives, key=lambda row: row["score"])
    return {
        "accepted": bool(best["accepted"]),
        "probe_only": False,
        "score": int(best["score"]),
        "role": role,
        "reason": (
            "Candidate metadata matches the requested gameplay motion."
            if best["accepted"]
            else "Candidate metadata does not prove the requested gameplay motion."
        ),
        "best_match": best,
        "alternatives": alternatives,
        "contracts": contracts,
    }
