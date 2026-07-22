"""Resume Unreal animation feature planning after a project-sight choice."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from urllib.parse import quote_plus

from tech_connector.services.autonomous_knowledge_retrieval_engine import (
    AutonomousKnowledgeRetrievalEngine,
)
from tech_connector.services.external_asset_acquisition_service import (
    search_asset_candidates,
)
from tech_connector.services.unreal.animation_context_service import (
    animation_role_contracts,
    infer_animation_roles,
)
from tech_connector.services.open_knowledge_policy_service import (
    partition_open_knowledge_sources,
)
from tech_connector.services.knowledge_credits_service import (
    register_open_knowledge_sources,
)


KNOWLEDGE_CHOICES = ("add_knowledge_first", "run_with_current_knowledge")
KNOWLEDGE_NEXT_ACTIONS = ("research_online", "continue_offline", "cancel")


def _clarification_values(binding: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(binding or {})
    execution_request = dict(payload.get("execution_request") or {})
    return dict(
        payload.get("values")
        or payload.get("resolved_slots")
        or payload.get("slot_values")
        or execution_request.get("keyword_args")
        or {}
    )


def resolve_animation_knowledge_choice(
    prompt: str,
    prior_result_metadata: dict[str, Any] | None,
    clarification_binding: dict[str, Any] | None = None,
) -> str:
    """Resolve only a choice bound to a prior Unreal knowledge gate."""

    prior = dict(prior_result_metadata or {})
    if prior.get("result_type") != "unreal_feature_knowledge_choice":
        return ""
    plan = dict(prior.get("plan") or {})
    if plan.get("status") != "knowledge_choice_required":
        return ""

    values = _clarification_values(clarification_binding)
    raw = str(values.get("knowledge_strategy") or prompt or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if normalized in KNOWLEDGE_CHOICES:
        return normalized
    if re.search(r"\b(add|gather|research|deepen|refresh)\b.*\bknowledge\b", raw):
        return "add_knowledge_first"
    if re.search(r"\b(run|continue|prototype|work)\b.*\b(current|offline|existing)\b", raw):
        return "run_with_current_knowledge"
    return ""


def resolve_animation_knowledge_next_action(
    prompt: str,
    prior_result_metadata: dict[str, Any] | None,
    clarification_binding: dict[str, Any] | None = None,
) -> str:
    """Resolve a continuation action only from its bound prior result."""

    prior = dict(prior_result_metadata or {})
    if prior.get("result_type") != "unreal_animation_knowledge_continuation":
        return ""
    values = _clarification_values(clarification_binding)
    raw = str(values.get("knowledge_next_action") or prompt or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if normalized in KNOWLEDGE_NEXT_ACTIONS:
        return normalized
    return ""


def _project_root(settings: dict[str, Any]) -> str:
    return str(settings.get("active_project") or settings.get("project_root") or "")


def _research_targets(request: str, roles: list[str]) -> list[dict[str, Any]]:
    """Create provider-specific searches, not fabricated asset candidates."""

    role_queries = []
    for role in roles:
        contracts = animation_role_contracts(role)
        terms = [role.replace("_", " "), "animation", "FBX"]
        if contracts:
            terms.extend(list(contracts[0].get("supporting_terms") or [])[:3])
        role_queries.append(" ".join(dict.fromkeys(terms)))
    if not role_queries:
        role_queries = [request[:180] + " animation FBX"]

    providers = (
        (
            "Fab",
            "Fab/Epic license and listing entitlement must be reviewed before acquisition.",
            "https://www.fab.com/search?q={query}",
        ),
        (
            "Mixamo",
            "Adobe account and Mixamo terms apply; export requires an authenticated browser session.",
            "https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack&query={query}",
        ),
        (
            "ActorCore",
            "Commercial listing terms and account entitlement must be reviewed.",
            "https://actorcore.reallusion.com/3d-motion?search={query}",
        ),
        (
            "Rokoko",
            "Motion Library listing terms and account entitlement must be reviewed.",
            "https://www.rokoko.com/motion-library?search={query}",
        ),
    )
    targets = []
    for query in role_queries:
        for provider, license_note, template in providers:
            targets.append(
                {
                    "provider": provider,
                    "query": query,
                    "url": template.format(query=quote_plus(query)),
                    "license_note": license_note,
                    "candidate_status": "research_target_not_asset_candidate",
                    "knowledge_use": "asset_discovery_only",
                    "learning_eligible": False,
                    "learning_reason": "A marketplace search result is not open reusable knowledge.",
                    "requires_online_access": True,
                }
            )
    return targets


def build_animation_knowledge_continuation(
    prior_plan: dict[str, Any],
    choice: str,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gather reusable evidence or prepare a constrained offline prototype."""

    plan = dict(prior_plan or {})
    settings = dict(settings or {})
    request = str(plan.get("request") or "")
    roles = infer_animation_roles(request)
    missing = list(plan.get("missing_capabilities") or [])
    acquisition_error = ""
    try:
        acquisition = AutonomousKnowledgeRetrievalEngine(
            project_root=_project_root(settings) or None,
        ).build_acquisition_plan(request, gaps=missing)
    except (OSError, PermissionError) as exc:
        acquisition_error = str(exc)
        try:
            acquisition = AutonomousKnowledgeRetrievalEngine().build_acquisition_plan(
                request,
                gaps=missing,
            )
        except Exception as fallback_exc:
            acquisition_error += "; fallback: " + str(fallback_exc)
            acquisition = {}
    local_channels = search_asset_candidates(
        request,
        asset_type="animation",
        target_host="unreal",
        limit=12,
        settings=settings,
        active_only=True,
    )
    accepted_local = [row for row in local_channels if row.get("contextually_usable") is True]
    open_knowledge = partition_open_knowledge_sources(
        [
            row
            for row in acquisition.get("local_records") or []
            if row.get("url") or row.get("source_url")
        ]
    )
    credits_error = ""
    credits_result: dict[str, Any] = {}
    if open_knowledge["accepted"]:
        try:
            credits_result = register_open_knowledge_sources(
                open_knowledge["accepted"],
                what_learned=request,
                domains=["unreal", "animation", *roles],
            )
        except (OSError, PermissionError) as exc:
            credits_error = str(exc)

    base = {
        "framework": "unreal_animation_knowledge_continuation_v1",
        "choice": choice,
        "request": request,
        "target_asset": plan.get("target_asset"),
        "target_mesh": (plan.get("evidence") or {}).get("skeletal_mesh"),
        "target_anim_blueprint": (plan.get("evidence") or {}).get("animation_blueprint"),
        "animation_roles": roles,
        "role_contracts": {
            role: animation_role_contracts(role) for role in roles
        },
        "local_knowledge": {
            "project_context": acquisition.get("project_context") or [],
            "knowledge_records": acquisition.get("local_records") or [],
            "provider_channels": local_channels,
            "contextually_accepted_assets": accepted_local,
            "warnings": [acquisition_error] if acquisition_error else [],
        },
        "open_knowledge_policy": {
            "required": True,
            "accepted_sources": open_knowledge["accepted"],
            "rejected_sources": open_knowledge["rejected"],
            "credits_registration": credits_result,
            "rules": [
                "Only public HTTPS information with open reuse terms or official public-documentation status may become reusable knowledge.",
                "Authenticated, paid, private, or project-confidential information is never promoted to shared knowledge.",
                "Marketplace metadata and licensed assets may support the current authorized task but remain asset records, not learned knowledge.",
            ],
        },
        "missing_capabilities": missing,
        "completion_allowed": False,
    }
    if credits_error:
        base["local_knowledge"]["warnings"].append(
            "Knowledge credits registry could not be updated: " + credits_error
        )

    if choice == "add_knowledge_first":
        online_allowed = bool(
            settings.get("enable_live_sources")
            and settings.get("research_web_techniques")
        )
        return {
            **base,
            "status": "online_research_ready" if online_allowed else "offline_knowledge_ready",
            "recommended": "research_online" if online_allowed else "continue_offline",
            "online_allowed": online_allowed,
            "research_queries": acquisition.get("research_queries") or [],
            "research_targets": _research_targets(request, roles),
            "candidate_acceptance": {
                "required": [
                    "clip-level title or description matches every requested role",
                    "preview or motion metadata supports posture and direction",
                    "downloadable animation format is identified",
                    "license and entitlement are recorded",
                    "source URL and provider are recorded",
                    "skeleton compatibility is measured or retargeting is required",
                ],
                "reject": [
                    "provider homepage without a clip listing",
                    "uncertain or absent license",
                    "generic locomotion substituted for a contextual role",
                    "metadata-only compatibility claim",
                ],
            },
            "next_choices": ["research_online", "continue_offline", "cancel"],
        }

    return {
        **base,
        "status": "offline_prototype_ready" if accepted_local else "offline_prototype_blocked",
        "recommended": "inspect_local_assets" if accepted_local else "add_knowledge_first",
        "online_allowed": False,
        "prototype_constraints": [
            "Create only isolated/removable prototype assets.",
            "Do not substitute generic animations for missing contextual roles.",
            "Do not claim completion without compile and matching PIE playback evidence.",
            "Stop before animation integration when no accepted local clip satisfies a role.",
        ],
        "blocked_roles": roles if not accepted_local else [],
        "next_choices": ["inspect_local_assets", "add_knowledge_first", "cancel"],
    }


def render_animation_knowledge_continuation(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "")
    lines = [
        "Animation knowledge continuation",
        "",
        f"Target: `{result.get('target_asset') or 'unresolved'}`",
        "Required roles: " + ", ".join(f"`{role}`" for role in result.get("animation_roles") or []),
    ]
    local = dict(result.get("local_knowledge") or {})
    accepted = list(local.get("contextually_accepted_assets") or [])
    lines.append(f"Contextually accepted local assets: `{len(accepted)}`")
    if status == "online_research_ready":
        lines.extend(
            [
                "",
                "Online research is available and recommended.",
                "The listed URLs are search targets, not approved animation candidates. A clip must pass contextual, license, format, and skeleton checks before download.",
            ]
        )
        for row in list(result.get("research_targets") or [])[:8]:
            lines.append(
                f"- [{row.get('provider')}: {row.get('query')}]({row.get('url')})"
            )
        lines.extend(["", "Choose `research_online`, `continue_offline`, or `cancel`."])
    elif status == "offline_knowledge_ready":
        lines.extend(
            [
                "",
                "Online research is disabled or unavailable. Local knowledge was refreshed.",
                "Choose `continue_offline` for an isolated prototype or `cancel`.",
            ]
        )
    elif status == "offline_prototype_blocked":
        lines.extend(
            [
                "",
                "The offline prototype is blocked because no local animation satisfies the required roles.",
                "No Unreal assets were changed. Choose `add_knowledge_first` or `cancel`.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "The offline prototype may continue only with isolated assets and the listed verification constraints.",
            ]
        )
    return "\n".join(lines)
