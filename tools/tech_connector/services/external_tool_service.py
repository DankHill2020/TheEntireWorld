"""External tool review, manifest, and ranking helpers."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


RISKY_FILES = {
    "setup.py",
    "pyproject.toml",
    "requirements.txt",
    "environment.yml",
    "package.json",
}


def repo_preflight_summary(repo: dict) -> dict:
    """Build a lightweight suitability summary from GitHub search/API metadata."""
    language = (repo.get("language") or "").lower()
    license_info = repo.get("license") or {}
    license_name = license_info.get("spdx_id") or license_info.get("name") or ""
    size_kb = int(repo.get("size") or 0)
    archived = bool(repo.get("archived", False))

    risks = []
    if archived:
        risks.append("archived")
    if size_kb > 150_000:
        risks.append("large repository")
    if language and language not in {"python", "mel", "c++", "c#", "javascript"}:
        risks.append(f"primary language is {repo.get('language')}")
    if not license_name:
        risks.append("license unknown")

    if archived or size_kb > 300_000:
        rating = "Risky"
    elif risks:
        rating = "Review"
    else:
        rating = "Good candidate"

    return {
        "rating": rating,
        "risks": risks,
        "language": repo.get("language") or "",
        "license": license_name,
        "size_kb": size_kb,
        "updated_at": repo.get("updated_at") or "",
    }


def analyze_installed_tool(repo_dir: Path, repo_info: Optional[dict] = None) -> dict:
    """Create an auditable manifest for an ingested external repository."""
    repo_dir = Path(repo_dir)
    py_files = list(repo_dir.rglob("*.py")) if repo_dir.exists() else []
    risky_files = []
    for path in repo_dir.rglob("*") if repo_dir.exists() else []:
        if path.is_file() and path.name.lower() in RISKY_FILES:
            risky_files.append(str(path.relative_to(repo_dir)))

    disabled = not py_files
    risks = []
    if disabled:
        risks.append("no Python files found")
    if risky_files:
        risks.append("dependency or install files present")

    manifest = {
        "schema": "ai_studio.external_tool.v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "repo": repo_info or {},
        "path": str(repo_dir),
        "python_files": len(py_files),
        "risky_files": risky_files[:50],
        "risks": risks,
        "disabled": disabled,
        "status": "disabled" if disabled else "available",
    }

    manifest_path = repo_dir / "ai_studio_tool_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def score_symbol(symbol: dict, goal: str, host: str = "") -> int:
    """Rank a discovered function/class by rough workflow relevance."""
    from tech_connector.services.capability_service import infer_symbol_contract

    text = " ".join(
        str(symbol.get(key, ""))
        for key in ("name", "signature", "file_path", "kind", "source")
    ).lower()
    contract = infer_symbol_contract(symbol)
    contract_types = " ".join(contract.get("categories", []))
    goal_tokens = [
        token
        for token in goal.lower().replace("_", " ").split()
        if len(token) >= 3
    ]
    score = 0
    for token in set(goal_tokens):
        if token in text:
            score += 3
    for strong in ("maya", "cmds", "joint", "bone", "slot", "rig", "control", "bake", "export"):
        if strong in goal.lower() and strong in text:
            score += 8
    if host and host.lower() in text:
        score += 10
    if symbol.get("kind") == "function":
        score += 2
    for category in contract.get("categories", []):
        if category in goal.lower() or category in contract_types:
            score += 4
    return score


def rank_symbols(symbols: list[dict], goal: str, host: str = "", limit: Optional[int] = None) -> list[dict]:
    ranked = []
    for symbol in symbols:
        item = dict(symbol)
        from tech_connector.services.capability_service import infer_symbol_contract

        item["contract"] = infer_symbol_contract(item)
        item["score"] = score_symbol(item, goal, host=host)
        ranked.append(item)
    ranked.sort(key=lambda item: item.get("score", 0), reverse=True)
    return ranked[:limit] if limit else ranked
