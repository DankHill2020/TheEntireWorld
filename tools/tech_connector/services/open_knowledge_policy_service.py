"""Trust policy for information that may become reusable system knowledge."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


OPEN_REUSE_MARKERS = {
    "cc0",
    "cc by",
    "cc-by",
    "creative commons attribution",
    "mit",
    "apache-2.0",
    "apache 2.0",
    "bsd",
    "public domain",
    "free for all uses",
    "official public documentation",
}


def assess_open_knowledge_source(source: dict[str, Any]) -> dict[str, Any]:
    """Decide whether a source may be promoted into reusable knowledge."""

    item = dict(source or {})
    url = str(item.get("url") or item.get("source_url") or "").strip()
    parsed = urlparse(url)
    access = str(item.get("access") or item.get("access_class") or "").lower()
    license_text = str(item.get("license") or item.get("reuse_terms") or "").lower()
    auth_required = bool(item.get("auth_required"))
    authenticated = bool(item.get("authenticated") or item.get("account_connected"))
    private = bool(item.get("private") or item.get("contains_private_data"))
    paid = bool(item.get("paid") or item.get("purchase_required"))
    entitlement_verified = bool(item.get("user_entitled") or item.get("entitlement_verified"))
    task_use_approved = bool(item.get("allow_task_use") or item.get("use_for_current_task"))
    local_learning_opt_in = bool(item.get("allow_local_learning") or item.get("local_training_opt_in"))
    official_public_docs = bool(item.get("official_public_documentation"))
    public_access = bool(
        item.get("public_access")
        or access in {"public", "open"}
        or official_public_docs
    )
    open_reuse = bool(
        official_public_docs
        or any(marker in license_text for marker in OPEN_REUSE_MARKERS)
    )
    reasons = []
    if parsed.scheme != "https":
        reasons.append("Knowledge sources must use HTTPS.")
    if not public_access:
        reasons.append("Public unauthenticated access is not proven.")
    if auth_required:
        reasons.append("Authenticated information cannot be promoted to reusable knowledge.")
    if private:
        reasons.append("Private or project-confidential information cannot be shared or learned globally.")
    if paid:
        reasons.append("Paid content may be used for an authorized task but cannot become reusable learned knowledge.")
    if not open_reuse:
        reasons.append("Open reuse terms or official public-documentation status are not proven.")

    eligible = not reasons
    restricted_access_verified = bool(
        parsed.scheme == "https"
        and task_use_approved
        and entitlement_verified
        and (not auth_required or authenticated)
    )
    public_task_use = bool(
        parsed.scheme == "https"
        and public_access
        and not auth_required
        and not private
        and not paid
    )
    task_use_allowed = bool(eligible or public_task_use or restricted_access_verified)
    local_learning_allowed = bool(
        eligible or (restricted_access_verified and local_learning_opt_in)
    )
    return {
        "eligible": eligible,
        "url": url,
        "access_class": "public" if public_access else "restricted_or_unknown",
        "reuse_class": "open" if open_reuse else "restricted_or_unknown",
        "task_use_allowed": task_use_allowed,
        "local_learning_allowed": local_learning_allowed,
        "restricted_access_verified": restricted_access_verified,
        "community_share_allowed": eligible,
        "reasons": reasons,
    }


def partition_open_knowledge_sources(
    sources: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    accepted = []
    rejected = []
    for source in sources:
        assessment = assess_open_knowledge_source(source)
        row = {**dict(source), "knowledge_policy": assessment}
        (accepted if assessment["eligible"] else rejected).append(row)
    return {"accepted": accepted, "rejected": rejected}
