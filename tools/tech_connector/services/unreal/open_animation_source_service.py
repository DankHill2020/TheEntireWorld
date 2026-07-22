"""Open, metadata-backed animation discovery for prompt continuations."""

from __future__ import annotations

import csv
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
from typing import Any
import urllib.parse
import urllib.request

from tech_connector.services.knowledge_credits_service import (
    register_open_knowledge_sources,
)
from tech_connector.services.public_https_service import create_public_https_context
from tech_connector.services.external_asset_acquisition_service import (
    download_asset_candidate,
)
from tech_connector.services.unreal.animation_context_service import (
    animation_role_contracts,
    evaluate_animation_candidate,
    infer_animation_roles,
)


CMU_SEARCH_URL = "https://mocap.cs.cmu.edu/search.php"
CMU_BASE_URL = "https://mocap.cs.cmu.edu"
CMU_FBX_BASE_URL = "https://huggingface.co/datasets/gbionics/cmu-fbx/resolve/main/animations"
CMU_FBX_METADATA_URL = "https://huggingface.co/datasets/gbionics/cmu-fbx/resolve/main/metadata.csv"
CMU_USAGE_TERMS = "Free for all uses; direct resale of the source data is prohibited."
CANDIDATE_ACTIONS = ("download_recommended_open_matches", "continue_offline", "cancel")


class _MotionTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = {"cells": [], "links": []}
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "a" and self._row is not None:
            href = dict(attrs).get("href") or ""
            if href:
                self._row["links"].append(str(href))

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row["cells"].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None


def parse_cmu_motion_results(html: str) -> list[dict[str, Any]]:
    """Parse CMU's result table while preserving subject/trial relationships."""

    parser = _MotionTableParser()
    parser.feed(str(html or ""))
    current_subject = ""
    current_skeleton_url = ""
    motions: list[dict[str, Any]] = []
    for row in parser.rows:
        cells = list(row.get("cells") or [])
        links = list(row.get("links") or [])
        row_text = " ".join(cells)
        subject_match = re.search(r"Subject\s*#(\d+)", row_text, re.IGNORECASE)
        if subject_match:
            current_subject = subject_match.group(1)
            skeleton_link = next((link for link in links if link.lower().endswith(".asf")), "")
            current_skeleton_url = urllib.parse.urljoin(CMU_BASE_URL, skeleton_link)
            continue
        if len(cells) < 3 or not cells[1].isdigit() or not current_subject:
            continue
        amc_link = next((link for link in links if link.lower().endswith(".amc")), "")
        if not amc_link:
            continue
        trial = cells[1]
        subject_padded = current_subject.zfill(2)
        trial_padded = trial.zfill(2)
        motions.append(
            {
                "clip_id": f"{subject_padded}_{trial_padded}",
                "subject_id": current_subject,
                "trial_id": trial,
                "description": cells[2],
                "skeleton_url": current_skeleton_url,
                "amc_url": urllib.parse.urljoin(CMU_BASE_URL, amc_link),
                "preview_url": urllib.parse.urljoin(
                    CMU_BASE_URL,
                    next((link for link in links if link.lower().endswith((".avi", ".mpg"))), ""),
                ),
                "download_url": f"{CMU_FBX_BASE_URL}/{subject_padded}_{trial_padded}.fbx",
            }
        )
    return motions


def parse_cmu_fbx_metadata_csv(payload: str) -> list[dict[str, Any]]:
    """Parse the verified FBX mirror's clip-level metadata catalog."""

    motions: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(str(payload or ""))):
        filename = str(row.get("file_name") or "").strip()
        match = re.fullmatch(r"(\d+)[_-](\d+)\.fbx", filename, re.IGNORECASE)
        if not match:
            continue
        subject, trial = match.groups()
        clip_id = f"{subject.zfill(2)}_{trial.zfill(2)}"
        motions.append(
            {
                "clip_id": clip_id,
                "subject_id": subject,
                "trial_id": trial,
                "description": str(row.get("description") or row.get("label") or "").strip(),
                "skeleton_url": "",
                "amc_url": "",
                "preview_url": "",
                "download_url": f"{CMU_FBX_BASE_URL}/{clip_id}.fbx",
            }
        )
    return motions


def _search_terms_for_role(role: str) -> list[str]:
    contracts = animation_role_contracts(role)
    terms: list[str] = []
    for contract in contracts:
        terms.extend(str(value) for value in contract.get("required_terms") or [])
        terms.extend(str(value) for value in contract.get("supporting_terms") or [])
    terms.extend(str(role or "").replace("_", " ").split())
    return [term for index, term in enumerate(terms) if term and term not in terms[:index]][:4]


def _fetch_cmu_search(term: str, timeout: float) -> str:
    payload = urllib.parse.urlencode(
        {
            "subjectnumber": "",
            "motion": term,
            "searchtype": "subjectnumberandormotion",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        CMU_SEARCH_URL,
        data=payload,
        headers={"User-Agent": "TechConnectorOpenAnimationResearch/1.0"},
    )
    with urllib.request.urlopen(
        request,
        timeout=timeout,
        context=create_public_https_context(),
    ) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch_cmu_fbx_metadata(timeout: float) -> str:
    request = urllib.request.Request(
        CMU_FBX_METADATA_URL,
        headers={"User-Agent": "TechConnectorOpenAnimationResearch/1.0"},
    )
    with urllib.request.urlopen(
        request,
        timeout=timeout,
        context=create_public_https_context(),
    ) as response:
        return response.read(4 * 1024 * 1024).decode("utf-8", errors="replace")


def search_open_animation_candidates(
    request: str,
    roles: list[str],
    *,
    limit_per_role: int = 5,
    timeout: float = 20.0,
    fetcher=None,
) -> dict[str, Any]:
    """Search open motion metadata and return only semantic role matches."""

    candidates_by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    searched_terms: list[dict[str, str]] = []
    catalog: list[dict[str, Any]] | None = None
    if fetcher is None:
        try:
            catalog = parse_cmu_fbx_metadata_csv(_fetch_cmu_fbx_metadata(timeout))
        except Exception as exc:
            errors.append(f"CMU FBX metadata search failed: {exc}")
            catalog = []
    for role in roles:
        accepted_for_role = 0
        terms = _search_terms_for_role(role)
        for term in terms:
            searched_terms.append({"role": role, "term": term})
        if catalog is not None:
            normalized_terms = [term.lower() for term in terms]
            motion_batches = [
                (
                    "metadata_catalog",
                    [
                        motion
                        for motion in catalog
                        if any(term in str(motion.get("description") or "").lower() for term in normalized_terms)
                    ],
                )
            ]
        else:
            motion_batches = []
            for term in terms:
                try:
                    motion_batches.append((term, parse_cmu_motion_results(fetcher(term, timeout))))
                except Exception as exc:
                    errors.append(f"CMU search failed for {role}/{term}: {exc}")
                    break
        for term, motions in motion_batches:
            try:
                motion_rows = list(motions)
            except TypeError as exc:
                errors.append(f"CMU search returned invalid rows for {role}/{term}: {exc}")
                continue
            for motion in motion_rows:
                candidate = {
                    **motion,
                    "name": f"CMU {motion['clip_id']}: {motion['description']}",
                    "provider": "CMU Graphics Lab / gbionics FBX conversion",
                    "source_url": CMU_FBX_METADATA_URL if catalog is not None else CMU_SEARCH_URL,
                    "license": CMU_USAGE_TERMS,
                    "public_access": True,
                    "download_available": True,
                    "asset_type": "animation",
                    "formats": ["fbx"] if catalog is not None else ["fbx", "amc", "asf"],
                    "target_hosts": ["unreal", "maya", "blender"],
                    "requires_retarget": True,
                    "source_skeleton": (
                        "CMU-derived bones-only FBX armature with hip root"
                        if catalog is not None
                        else "CMU subject-specific ASF skeleton"
                    ),
                }
                semantic = evaluate_animation_candidate(role, candidate)
                if not semantic.get("accepted"):
                    continue
                current = candidates_by_id.setdefault(
                    motion["clip_id"],
                    {**candidate, "matched_roles": [], "semantic_evidence": {}},
                )
                if role not in current["matched_roles"]:
                    current["matched_roles"].append(role)
                current["semantic_evidence"][role] = semantic
                accepted_for_role += 1
                if accepted_for_role >= max(1, int(limit_per_role)):
                    break
            if accepted_for_role >= max(1, int(limit_per_role)):
                break

    candidates = sorted(
        candidates_by_id.values(),
        key=lambda row: (
            -len(row.get("matched_roles") or []),
            -max(
                [int(item.get("score") or 0) for item in (row.get("semantic_evidence") or {}).values()]
                or [0]
            ),
            str(row.get("clip_id") or ""),
        ),
    )
    covered_roles = sorted({role for row in candidates for role in row.get("matched_roles") or []})
    missing_roles = [role for role in roles if role not in covered_roles]
    credits = register_open_knowledge_sources(
        [
            {
                "title": "CMU Graphics Lab Motion Capture Database",
                "organization": "Carnegie Mellon University",
                "url": "https://mocap.cs.cmu.edu/faqs.php",
                "official_public_documentation": True,
                "public_access": True,
                "license": "Official public documentation and CMU dataset usage terms",
                "attribution": "The data used in this project was obtained from mocap.cs.cmu.edu.",
            },
            {
                "title": "CMU mocap FBX conversion",
                "creator": "gbionics",
                "url": "https://huggingface.co/datasets/gbionics/cmu-fbx",
                "public_access": True,
                "license": CMU_USAGE_TERMS,
                "attribution": "FBX conversion derived from CMU mocap and Bruce Hahn's BVH conversion.",
            },
        ],
        what_learned="Open animation discovery and clip metadata for: " + str(request or ""),
        domains=["animation", "mocap", "unreal", *roles],
    )
    return {
        "status": "online_candidates_found" if candidates else "online_candidates_not_found",
        "provider": "cmu_open_mocap_fbx",
        "request": request,
        "roles": roles,
        "candidates": candidates,
        "covered_roles": covered_roles,
        "missing_roles": missing_roles,
        "searched_terms": searched_terms,
        "errors": errors,
        "credits_registration": credits,
        "completion_allowed": False,
    }


def _plan_animation_roles(plan: dict[str, Any]) -> list[str]:
    roles = list(plan.get("animation_roles") or [])
    if not roles:
        roles = list((plan.get("behavior_decomposition") or {}).get("animation_roles") or [])
    if not roles:
        roles = infer_animation_roles(str(plan.get("request") or ""))
    return list(dict.fromkeys(str(role) for role in roles if str(role).strip()))


def _locally_covered_animation_roles(plan: dict[str, Any]) -> set[str]:
    covered: set[str] = set()
    for assessment in list(plan.get("animation_role_assessment") or []):
        role = str(assessment.get("role") or "")
        for row in list(assessment.get("semantic_candidates") or []):
            candidate = dict(row.get("candidate") or {})
            evaluation = dict(row.get("evaluation") or {})
            path = str(candidate.get("path") or "")
            source = str(candidate.get("source") or "")
            if evaluation.get("accepted") is True and (
                path.startswith("/Game/") or source == "asset_registry"
            ):
                covered.add(role)
                break
    return covered


def enrich_plan_with_automatic_open_animation_research(
    plan: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    searcher=None,
) -> dict[str, Any]:
    """Search open motion sources when live inventory has no accepted local role asset.

    Discovery is read-only. Candidates remain metadata-only until an approved plan
    downloads, retargets, imports, previews, and proves them in PIE.
    """

    enriched = dict(plan or {})
    settings = dict(settings or {})
    roles = _plan_animation_roles(enriched)
    covered = _locally_covered_animation_roles(enriched)
    missing_roles = [role for role in roles if role not in covered]
    if not roles:
        enriched["automatic_animation_asset_research"] = {
            "status": "not_required",
            "roles": [],
            "completion_allowed": False,
        }
        return enriched
    if not missing_roles:
        enriched["automatic_animation_asset_research"] = {
            "status": "local_candidates_available",
            "roles": roles,
            "covered_roles": sorted(covered),
            "missing_roles": [],
            "completion_allowed": False,
        }
        return enriched
    if not settings.get("auto_search_missing_public_assets", True):
        enriched["automatic_animation_asset_research"] = {
            "status": "automatic_search_disabled",
            "roles": roles,
            "covered_roles": sorted(covered),
            "missing_roles": missing_roles,
            "completion_allowed": False,
        }
        return enriched

    lookup = searcher or search_open_animation_candidates
    try:
        research = lookup(
            str(enriched.get("request") or ""),
            missing_roles,
        )
    except Exception as exc:
        research = {
            "status": "online_search_failed",
            "roles": missing_roles,
            "candidates": [],
            "covered_roles": [],
            "missing_roles": missing_roles,
            "errors": [str(exc)],
            "completion_allowed": False,
        }
    research["policy"] = {
        "automatic_sources": "public_open_only",
        "authenticated_or_paid_sources": "never_queried_without_explicit_user_selection",
        "download_requires_approved_plan": True,
        "contextual_preview_required": True,
    }
    research["requested_missing_local_roles"] = missing_roles
    enriched["automatic_animation_asset_research"] = research

    capability = "animation.acquire_contextual_role_assets"
    missing_capabilities = list(enriched.get("missing_capabilities") or [])
    if not any(str(row.get("capability") or "") == capability for row in missing_capabilities):
        missing_capabilities.append(
            {
                "capability": capability,
                "reason": (
                    "No accepted local animation exists for: " + ", ".join(missing_roles) + ". "
                    "Online results are candidates only until download, retarget/import, contextual preview, and PIE playback pass."
                ),
                "registered": True,
                "function": "open_animation_source_service.search_open_animation_candidates",
            }
        )
    enriched["missing_capabilities"] = missing_capabilities
    acquisition = list(enriched.get("capability_acquisition") or [])
    if not any(str(row.get("capability") or "") == capability for row in acquisition):
        acquisition.append(
            {
                "step": len(acquisition) + 1,
                "capability": capability,
                "current_evidence": {
                    "reason": "Local role inventory is incomplete.",
                    "missing_roles": missing_roles,
                    "online_candidate_count": len(research.get("candidates") or []),
                },
                "actions": [
                    "Present public open candidates and provenance in the implementation plan.",
                    "After exact-plan approval, download selected files into the project's ArtSource acquisition folder.",
                    "Measure source/target skeleton compatibility and retarget when required.",
                    "Import into the selected Unreal destination without modifying source animation assets.",
                    "Reject the clip unless contextual target-character preview and PIE playback prove the requested role.",
                ],
                "done_when": (
                    "Every missing role has a licensed, provenance-recorded, skeleton-compatible Unreal asset "
                    "that passes contextual preview and runtime playback evidence."
                ),
            }
        )
    enriched["capability_acquisition"] = acquisition
    readiness = dict(enriched.get("build_readiness") or {})
    readiness["ready_to_execute"] = False
    readiness["blocked_by"] = list(
        dict.fromkeys([*list(readiness.get("blocked_by") or []), capability])
    )
    enriched["build_readiness"] = readiness
    if enriched.get("status") == "approval_ready":
        enriched["status"] = "capability_acquisition_required"
    return enriched


def resolve_open_animation_candidate_action(
    prompt: str,
    prior_result_metadata: dict[str, Any] | None,
    clarification_binding: dict[str, Any] | None = None,
) -> str:
    prior = dict(prior_result_metadata or {})
    if prior.get("result_type") != "unreal_animation_candidate_research":
        return ""
    binding = dict(clarification_binding or {})
    execution_request = dict(binding.get("execution_request") or {})
    values = dict(
        binding.get("values")
        or binding.get("resolved_slots")
        or binding.get("slot_values")
        or execution_request.get("keyword_args")
        or {}
    )
    raw = str(values.get("animation_candidate_action") or prompt or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return normalized if normalized in CANDIDATE_ACTIONS else ""


def _recommended_candidate_assignments(research: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assignments: dict[str, dict[str, Any]] = {}
    for candidate in list(research.get("candidates") or []):
        for role in candidate.get("matched_roles") or []:
            if role not in assignments:
                assignments[str(role)] = candidate
    return assignments


def download_recommended_open_animation_candidates(
    research: dict[str, Any],
    project_root: str | Path,
    *,
    destination: str = "AIStudio/DownloadedAnimations",
) -> dict[str, Any]:
    """Download one best metadata match per covered role with provenance."""

    root = Path(project_root).expanduser().resolve()
    cache_root = root / "ArtSource" / "AIStudio" / "Animations" / "OpenMocap"
    assignments = _recommended_candidate_assignments(research)
    downloads_by_clip: dict[str, dict[str, Any]] = {}
    ledger_entries: dict[str, dict[str, Any]] = {}
    role_downloads: dict[str, dict[str, Any]] = {}
    for role, candidate in assignments.items():
        clip_id = str(candidate.get("clip_id") or candidate.get("download_url") or "")
        if clip_id not in downloads_by_clip:
            approved_candidate = {
                **dict(candidate),
                "semantic_candidate_accepted_for_download": True,
                "contextual_preview_status": "pending",
                "completion_allowed": False,
                "animation_context": list((candidate.get("semantic_evidence") or {}).values()),
            }
            downloads_by_clip[clip_id] = download_asset_candidate(
                approved_candidate,
                cache_root,
                approved=True,
                target_host="unreal",
                destination=destination,
            )
            download = downloads_by_clip[clip_id]
            if download.get("ok"):
                from tech_connector.services.asset_provenance_ledger_service import (
                    register_external_asset,
                )

                manifest = dict(download.get("manifest") or {})
                ledger_entries[clip_id] = register_external_asset(
                    root,
                    {
                        **manifest,
                        "source_kind": "open_animation",
                        "semantic_roles": list(candidate.get("matched_roles") or []),
                        "license_scope": "open",
                    },
                )
        role_downloads[role] = {
            "clip_id": clip_id,
            "candidate": candidate,
            "download": downloads_by_clip[clip_id],
        }
    failed_roles = [
        role for role, row in role_downloads.items() if not (row.get("download") or {}).get("ok")
    ]
    missing_roles = list(research.get("missing_roles") or [])
    return {
        "status": (
            "downloaded_for_retarget_handoff"
            if role_downloads and not failed_roles
            else "animation_download_failed"
        ),
        "cache_root": str(cache_root),
        "role_downloads": role_downloads,
        "missing_roles": missing_roles,
        "failed_roles": failed_roles,
        "asset_ledger_entries": ledger_entries,
        "requires_target_skeleton_selection": bool(role_downloads and not failed_roles),
        "requires_retarget": True,
        "completion_allowed": False,
    }


def discover_live_retarget_target_options(
    preferred_skeleton: str = "",
    preferred_mesh: str = "",
) -> dict[str, Any]:
    """Ask the live Unreal project for Skeleton choices without fixed asset paths."""

    from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

    source = "\n".join(
        (
            "import json",
            "from tech_connector.bridges.unreal.unreal_dynamic_character_feature import discover_retarget_target_options",
            "result = discover_retarget_target_options(" + repr(str(preferred_skeleton or "")) + ", " + repr(str(preferred_mesh or "")) + ")",
            "print(json.dumps(result))",
        )
    )
    response = UnrealBridge().execute_python(source, timeout=30, reset_globals=True)
    if not response.get("ok"):
        return {"ok": False, "options": [], "default_target_skeleton": "", "errors": [str(response.get("error") or "Unreal target discovery failed.")]}
    data = response.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = {}
    return dict(data or {})


def render_open_animation_candidate_research(result: dict[str, Any]) -> str:
    lines = ["Open animation research", ""]
    lines.append("Covered roles: " + ", ".join(f"`{role}`" for role in result.get("covered_roles") or []) or "none")
    lines.append("Missing roles: " + ", ".join(f"`{role}`" for role in result.get("missing_roles") or []) or "none")
    lines.append("")
    for candidate in list(result.get("candidates") or [])[:12]:
        roles = ", ".join(candidate.get("matched_roles") or [])
        lines.append(
            f"- `{candidate.get('clip_id')}` {candidate.get('description')} ({roles}) "
            f"[preview]({candidate.get('preview_url')})"
        )
    if result.get("candidates"):
        lines.extend(
            [
                "",
                "These are metadata matches, not completed gameplay assets. Download preserves provenance; preview, retarget, import, compile, and PIE playback gates still apply.",
                "Choose `download_recommended_open_matches`, `continue_offline`, or `cancel`.",
            ]
        )
    else:
        lines.extend(["", "No open clip passed the semantic role contracts. No substitution will be made."])
    return "\n".join(lines)


def render_open_animation_download(result: dict[str, Any]) -> str:
    lines = ["Open animation download", ""]
    lines.append(f"Status: `{result.get('status')}`")
    lines.append(f"Project source folder: `{result.get('cache_root') or 'unresolved'}`")
    for role, row in (result.get("role_downloads") or {}).items():
        download = dict(row.get("download") or {})
        lines.append(
            f"- `{role}`: `{download.get('local_path') or 'download failed'}` "
            f"({download.get('bytes') or 0} bytes)"
        )
    if result.get("missing_roles"):
        lines.append("Missing roles remain blocked: " + ", ".join(f"`{role}`" for role in result["missing_roles"]))
    if result.get("requires_target_skeleton_selection"):
        lines.extend(["", "Select the live project Skeleton that should receive the retargeted animations."])
    return "\n".join(lines)
