"""External tool review, manifest, and ranking helpers."""

from __future__ import annotations

import json
import re
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

README_NAMES = (
    "README.md",
    "README.rst",
    "README.txt",
    "readme.md",
    "readme.rst",
    "readme.txt",
)

MANIFEST_NAMES = (
    "ai_studio_tool_manifest.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
)

OPEN_SOURCE_LICENSE_IDS = {
    "0bsd",
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "cc0-1.0",
    "epl-2.0",
    "gpl-2.0",
    "gpl-3.0",
    "isc",
    "lgpl-2.1",
    "lgpl-3.0",
    "mit",
    "mpl-2.0",
    "unlicense",
    "zlib",
}


def _read_limited(path: Path, limit: int = 12_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _first_readme(repo_dir: Path) -> tuple[Path | None, str]:
    for name in README_NAMES:
        path = repo_dir / name
        if path.exists() and path.is_file():
            return path, _read_limited(path)
    for path in repo_dir.rglob("*"):
        if path.is_file() and path.name in README_NAMES:
            return path, _read_limited(path)
    return None, ""


def _manifest_texts(repo_dir: Path) -> list[dict]:
    manifests: list[dict] = []
    for name in MANIFEST_NAMES:
        path = repo_dir / name
        if path.exists() and path.is_file():
            manifests.append({"path": str(path), "name": name, "text": _read_limited(path, limit=8_000)})
    return manifests


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text.lower().replace("-", "_"))
        if token not in {"the", "and", "for", "with", "from", "this", "that", "into", "using", "use"}
    }


def _snippet_around(text: str, needle: str, *, width: int = 180) -> str:
    if not text or not needle:
        return ""
    match = re.search(re.escape(needle), text, flags=re.IGNORECASE)
    if not match:
        return ""
    start = max(0, match.start() - width // 2)
    end = min(len(text), match.end() + width // 2)
    return " ".join(text[start:end].split())


def _relative_module(repo_dir: Path, file_path: str) -> str:
    path = Path(file_path)
    try:
        rel = path.resolve().relative_to(repo_dir.resolve())
    except Exception:
        rel = path.name
    if isinstance(rel, Path):
        parts = list(rel.with_suffix("").parts)
    else:
        parts = [str(rel)]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(part for part in parts if part)


def _confidence(score: int, top_score: int, candidate_count: int) -> float:
    if score <= 0:
        return 0.25
    base = min(0.96, 0.45 + (score / max(40, score + 10)) * 0.45)
    if candidate_count > 1 and top_score and score < top_score:
        base -= 0.1
    return round(max(0.1, min(0.98, base)), 2)


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


def license_priority(repo: dict) -> int:
    """Lower is better; open-source/free candidates should rank before unknown terms."""
    license_info = repo.get("license") or {}
    spdx = str(license_info.get("spdx_id") or "").strip().lower()
    name = str(license_info.get("name") or "").strip().lower()
    if spdx in OPEN_SOURCE_LICENSE_IDS:
        return 0
    if any(marker in name for marker in ("mit", "apache", "bsd", "gpl", "lgpl", "mpl", "cc0", "unlicense", "open source")):
        return 0
    if spdx or name:
        return 1
    return 2


def rank_github_candidate_repos(repos: list[dict], *, limit: Optional[int] = None) -> list[dict]:
    ranked = [dict(repo or {}) for repo in repos]
    ranked.sort(
        key=lambda repo: (
            license_priority(repo),
            bool(repo.get("archived", False)),
            -int(repo.get("stars") or repo.get("stargazers_count") or 0),
            str(repo.get("name") or repo.get("full_name") or "").lower(),
        )
    )
    return ranked[:limit] if limit else ranked


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


def verify_external_tool_for_pipeline(
    repo_dir: Path,
    goal: str = "",
    *,
    symbols: Optional[list[dict]] = None,
    repo_info: Optional[dict] = None,
    host: str = "",
    limit: Optional[int] = 5,
) -> dict:
    """Verify which downloaded callables are plausible pipeline entry points.

    README and manifest files are evidence for intent; AST-discovered symbols are
    the authority for what can be imported into a pipeline without executing the
    downloaded code.
    """
    from tech_connector.services.tool_discovery_service import list_ingested_tools

    repo_dir = Path(repo_dir)
    symbols = list(symbols if symbols is not None else list_ingested_tools(repo_dir))
    readme_path, readme_text = _first_readme(repo_dir)
    manifests = _manifest_texts(repo_dir)
    manifest_blob = "\n".join(item["text"] for item in manifests)
    evidence_blob = f"{readme_text}\n{manifest_blob}".lower()
    goal_tokens = _tokens(goal)
    repo_summary = repo_preflight_summary(repo_info or {})
    raw_ranked = rank_symbols(symbols, goal, host=host)
    candidates: list[dict] = []

    for symbol in raw_ranked:
        if symbol.get("kind") != "function":
            continue
        name = str(symbol.get("name") or "")
        if not name or name.startswith("_"):
            continue
        module_name = _relative_module(repo_dir, str(symbol.get("file_path") or ""))
        symbol_text = " ".join(
            str(symbol.get(key, ""))
            for key in ("name", "signature", "docstring", "file_path", "source")
        )
        symbol_tokens = _tokens(symbol_text)
        readme_mentions = []
        manifest_mentions = []
        if name.lower() in evidence_blob:
            snippet = _snippet_around(readme_text, name) or _snippet_around(manifest_blob, name)
            if snippet:
                readme_mentions.append(snippet)
        for token in sorted(goal_tokens & symbol_tokens)[:8]:
            snippet = _snippet_around(readme_text, token)
            if snippet:
                readme_mentions.append(snippet)
            manifest_snippet = _snippet_around(manifest_blob, token)
            if manifest_snippet:
                manifest_mentions.append(manifest_snippet)

        evidence_score = len(set(readme_mentions)) * 8 + len(set(manifest_mentions)) * 4
        code_score = int(symbol.get("score") or 0)
        if name.lower() in evidence_blob:
            evidence_score += 12
        score = code_score + evidence_score
        risk_notes = list(repo_summary.get("risks") or [])
        if symbol.get("params") and all(str(param.get("default", "")) == "" for param in symbol.get("params", [])):
            risk_notes.append("callable has required parameters; pipeline must supply or prompt for them")
        candidate = {
            "name": name,
            "kind": symbol.get("kind"),
            "file_path": symbol.get("file_path"),
            "line": symbol.get("lineno", 0),
            "signature": symbol.get("signature", ""),
            "docstring": symbol.get("docstring", ""),
            "params": symbol.get("params", []),
            "outputs": symbol.get("outputs", []),
            "import_module": module_name,
            "import_symbol": name,
            "entry_point": f"{module_name}.{name}" if module_name else name,
            "score": score,
            "verification": {
                "callable": True,
                "readme_mentions": list(dict.fromkeys(readme_mentions))[:3],
                "manifest_mentions": list(dict.fromkeys(manifest_mentions))[:3],
                "code_mentions": sorted(goal_tokens & symbol_tokens)[:8],
                "risk_notes": risk_notes,
            },
            "pipeline_use": {
                "node_name": name,
                "entry_point": f"{module_name}.{name}" if module_name else name,
                "source": "external_tools",
                "expected_args": symbol.get("params", []),
                "outputs": symbol.get("outputs", []),
                "requires_adapter": False,
            },
        }
        candidates.append(candidate)

    candidates.sort(key=lambda item: item.get("score", 0), reverse=True)
    candidates = candidates[:limit] if limit else candidates
    top_score = int(candidates[0]["score"]) if candidates else 0
    for candidate in candidates:
        candidate["confidence"] = _confidence(int(candidate.get("score") or 0), top_score, len(candidates))

    clear_winner = len(candidates) == 1 or (
        len(candidates) > 1
        and candidates[0]["confidence"] >= 0.75
        and int(candidates[0].get("score") or 0) >= int(candidates[1].get("score") or 0) + 12
    )
    return {
        "ok": bool(candidates),
        "status": "verified_candidates" if candidates else "no_pipeline_callable_found",
        "repo_dir": str(repo_dir),
        "repo": repo_info or {},
        "readme_path": str(readme_path) if readme_path else "",
        "readme_excerpt": " ".join(readme_text[:700].split()),
        "manifest_files": [item["path"] for item in manifests],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "requires_user_selection": not clear_winner,
        "verification_basis": [
            "AST symbol extraction confirms callable existence.",
            "README and manifest evidence rank intended usage.",
            "Downloaded code is not imported or executed during verification.",
        ],
    }


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
