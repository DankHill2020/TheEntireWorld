"""Capability Acquisition Engine — discovers, ranks, and executes acquisition strategies.

For each missing capability, discovers possible acquisition strategies from:
  Phase 1 (automated):
    - Internal codegen (build it ourselves)
    - GitHub public repos (via github_ingest_service)
    - Public documentation ingestion
  Phase 2 (semi-automated / requires user action):
    - Unreal Marketplace / Fab
    - Mixamo, ActorCore, Rokoko (animation sources)
    - Blender Extensions, Quixel, Poly Haven (asset sources)
    - AI services (video-to-animation, text-to-animation)

All strategies go through an ethics gate: only publicly accessible URLs are allowed.
No external code is auto-executed — everything is staged and requires approval.
"""

from __future__ import annotations

import json
import re
import traceback
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# AcquisitionStrategy
# ---------------------------------------------------------------------------

@dataclass
class AcquisitionStrategy:
    """A single ranked strategy for acquiring a missing capability."""

    id: str
    name: str
    source_type: str           # github | docs | codegen | manual | marketplace | asset_source | ai_service
    source_url: str
    description: str
    capabilities_provided: list   # list of capability keyword strings
    estimated_minutes: int
    success_probability: float    # 0.0–1.0
    cost: str                      # "Free", "$39", "Subscription"
    license: str
    automation_level: str          # "Full" | "Semi" | "Manual"
    compatibility: dict            # {"unreal": "5.x", "maya": "2024+"}
    risks: list
    ranking_score: float
    phase: int                     # 1 = automated, 2 = semi-automated


@dataclass
class AcquisitionResult:
    """Result of executing an acquisition strategy."""

    strategy_id: str
    success: bool
    message: str
    registered_capability_ids: list   # IDs added to registry
    local_path: str                    # where files landed


# ---------------------------------------------------------------------------
# Known capability sources catalog
# ---------------------------------------------------------------------------

KNOWN_CAPABILITY_SOURCES: dict = {
    # ----- Animation / Motion Capture -----
    "mixamo": {
        "name": "Mixamo",
        "source_type": "asset_source",
        "url": "https://www.mixamo.com",
        "provides": ["animation", "fbx_import", "character_animation", "retargeting", "mocap", "rigging"],
        "cost": "Free",
        "license": "Adobe Standard License",
        "automation": "Semi",
        "estimated_minutes": 15,
        "success_probability": 0.94,
        "compatibility": {"unreal": "5.x", "maya": "2024+", "blender": "4.x"},
        "phase": 2,
        "description": "Free character animations from Adobe. Download FBX files from mixamo.com and import via FBX pipeline.",
    },
    "actorcore": {
        "name": "ActorCore",
        "source_type": "asset_source",
        "url": "https://actorcore.reallusion.com",
        "provides": ["animation", "motion_library", "character_animation", "high_quality"],
        "cost": "Subscription",
        "license": "Commercial",
        "automation": "Manual",
        "estimated_minutes": 20,
        "success_probability": 0.90,
        "compatibility": {"unreal": "5.x", "maya": "2024+"},
        "phase": 2,
        "description": "High-quality motion library from Reallusion.",
    },
    "rokoko": {
        "name": "Rokoko Motion Library",
        "source_type": "asset_source",
        "url": "https://www.rokoko.com",
        "provides": ["mocap", "animation", "motion_library"],
        "cost": "Free / Subscription",
        "license": "Commercial",
        "automation": "Semi",
        "estimated_minutes": 20,
        "success_probability": 0.88,
        "compatibility": {"unreal": "5.x", "maya": "2024+", "blender": "4.x"},
        "phase": 2,
        "description": "Motion capture library with Blender plugin support.",
    },
    # ----- Unreal Resources -----
    "fab_marketplace": {
        "name": "Fab Marketplace",
        "source_type": "marketplace",
        "url": "https://www.fab.com",
        "provides": ["unreal_plugin", "asset", "blueprint", "animation"],
        "cost": "Varies",
        "license": "Fab/Epic License",
        "automation": "Semi",
        "estimated_minutes": 10,
        "success_probability": 0.95,
        "compatibility": {"unreal": "5.x"},
        "phase": 2,
        "description": "Unreal Engine asset marketplace (formerly UE Marketplace). Browse and install plugins/assets.",
    },
    "epic_sample_projects": {
        "name": "Epic Sample Projects",
        "source_type": "asset_source",
        "url": "https://docs.unrealengine.com/5.0/en-US/samples-and-tutorials-for-unreal-engine/",
        "provides": ["unreal_plugin", "sample", "blueprint", "motion_matching", "gameplay"],
        "cost": "Free",
        "license": "MIT / UE EULA",
        "automation": "Semi",
        "estimated_minutes": 30,
        "success_probability": 0.92,
        "compatibility": {"unreal": "5.x"},
        "phase": 2,
        "description": "Epic-provided sample projects for Unreal Engine 5.",
    },
    # ----- 3D Assets -----
    "poly_haven": {
        "name": "Poly Haven",
        "source_type": "asset_source",
        "url": "https://polyhaven.com",
        "provides": ["hdri", "texture", "3d_model", "material"],
        "cost": "Free",
        "license": "CC0",
        "automation": "Full",
        "estimated_minutes": 5,
        "success_probability": 0.98,
        "compatibility": {"unreal": "5.x", "blender": "4.x"},
        "phase": 2,
        "description": "Free CC0 HDRIs, textures, and 3D models.",
    },
    "quixel": {
        "name": "Quixel Bridge",
        "source_type": "asset_source",
        "url": "https://quixel.com/bridge",
        "provides": ["texture", "material", "3d_asset", "megascans"],
        "cost": "Free with Epic",
        "license": "UE EULA",
        "automation": "Semi",
        "estimated_minutes": 10,
        "success_probability": 0.93,
        "compatibility": {"unreal": "5.x"},
        "phase": 2,
        "description": "Quixel Megascans — photorealistic assets for Unreal Engine.",
    },
    # ----- Documentation -----
    "unreal_docs": {
        "name": "Unreal Engine Documentation",
        "source_type": "docs",
        "url": "https://docs.unrealengine.com",
        "provides": ["unreal_api", "documentation", "blueprint", "python", "gameplay"],
        "cost": "Free",
        "license": "Public",
        "automation": "Full",
        "estimated_minutes": 3,
        "success_probability": 0.99,
        "compatibility": {"unreal": "5.x"},
        "phase": 1,
        "description": "Official Unreal Engine 5 documentation.",
    },
    "maya_docs": {
        "name": "Maya Python Documentation",
        "source_type": "docs",
        "url": "https://help.autodesk.com/view/MAYAUL/2024/ENU/",
        "provides": ["maya_api", "documentation", "cmds", "python", "mel"],
        "cost": "Free",
        "license": "Public",
        "automation": "Full",
        "estimated_minutes": 3,
        "success_probability": 0.99,
        "compatibility": {"maya": "2024+"},
        "phase": 1,
        "description": "Official Autodesk Maya 2024 Python/cmds documentation.",
    },
    "blender_docs": {
        "name": "Blender Python API Documentation",
        "source_type": "docs",
        "url": "https://docs.blender.org/api/current/",
        "provides": ["blender_api", "documentation", "bpy", "python"],
        "cost": "Free",
        "license": "Public (GPL)",
        "automation": "Full",
        "estimated_minutes": 3,
        "success_probability": 0.99,
        "compatibility": {"blender": "4.x"},
        "phase": 1,
        "description": "Official Blender 4.x Python API documentation.",
    },
}


# ---------------------------------------------------------------------------
# Ethics gate
# ---------------------------------------------------------------------------

_PRIVATE_DOMAIN_PATTERNS = [
    r"localhost",
    r"127\.\d+\.\d+\.\d+",
    r"192\.168\.",
    r"10\.\d+\.\d+\.",
    r"172\.(1[6-9]|2\d|3[01])\.",
    r"\.internal\b",
    r"\.corp\b",
    r"\.local\b",
]

_ALLOWED_CODE_DOMAINS = {"github.com", "www.github.com"}


def is_public_url(url: str) -> bool:
    """Ethics gate: returns True only for publicly accessible, non-credential-gated URLs."""
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = parsed.netloc.lower()
        for pattern in _PRIVATE_DOMAIN_PATTERNS:
            if re.search(pattern, host):
                return False
        return True
    except Exception:
        return False


def is_allowed_code_url(url: str) -> bool:
    """Code ingestion is restricted to github.com public repositories only."""
    if not is_public_url(url):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc.lower() in _ALLOWED_CODE_DOMAINS
    except Exception:
        return False


# ---------------------------------------------------------------------------
# AcquisitionEngine
# ---------------------------------------------------------------------------

class AcquisitionEngine:
    """Discovers and executes acquisition strategies for missing capabilities."""

    def __init__(self, registry, project_root: Path) -> None:
        from tech_connector.services.capability_registry import CapabilityRegistry
        self._registry = registry
        self._project_root = Path(project_root)
        self._external_tools_dir = self._project_root / "external_tools"

    # ------------------------------------------------------------------
    # Strategy discovery
    # ------------------------------------------------------------------

    def discover_strategies(self, missing_requirements: list) -> list:
        """Discover possible acquisition strategies for a list of missing requirement strings."""
        strategies = []
        seen_ids: set = set()

        for requirement in missing_requirements:
            req_lower = requirement.lower()
            req_tokens = set(re.findall(r"[a-z][a-z0-9_]{2,}", req_lower))

            # 1. Internal codegen — always try first
            codegen = self._strategy_codegen(requirement)
            if codegen and codegen.id not in seen_ids:
                strategies.append(codegen)
                seen_ids.add(codegen.id)

            # 2. GitHub search (Phase 1)
            github = self._strategy_github_search(requirement, req_tokens)
            for s in github:
                if s.id not in seen_ids:
                    strategies.append(s)
                    seen_ids.add(s.id)

            # 3. Docs ingestion (Phase 1)
            docs = self._strategy_docs(requirement, req_tokens)
            for s in docs:
                if s.id not in seen_ids:
                    strategies.append(s)
                    seen_ids.add(s.id)

            # 4. Known sources catalog (Phase 1 docs + Phase 2 everything else)
            catalog = self._strategy_from_catalog(requirement, req_tokens)
            for s in catalog:
                if s.id not in seen_ids:
                    strategies.append(s)
                    seen_ids.add(s.id)

        return self.rank_strategies(strategies)

    def _strategy_codegen(self, requirement: str) -> Optional[AcquisitionStrategy]:
        """Strategy: generate an internal adapter/wrapper for the requirement."""
        return AcquisitionStrategy(
            id=f"codegen_{_slug(requirement)}",
            name=f"Generate internal adapter: {requirement}",
            source_type="codegen",
            source_url="",
            description=f"Auto-generate a Python adapter/wrapper that implements '{requirement}' using existing internal tools.",
            capabilities_provided=[requirement.lower()],
            estimated_minutes=2,
            success_probability=0.75,
            cost="Free",
            license="Internal",
            automation_level="Full",
            compatibility={"*": "*"},
            risks=["Generated code may require manual validation"],
            ranking_score=0.0,
            phase=1,
        )

    def _strategy_github_search(self, requirement: str, tokens: set) -> list:
        """Strategy: search GitHub for public repos matching the requirement."""
        strategies = []
        # Build a search query from the tokens
        query_terms = " ".join(sorted(tokens)[:4])
        query = f"{query_terms} python game-dev DCC"
        github_url = f"https://github.com/search?q={urllib.parse.quote(query)}&type=repositories"

        strategies.append(AcquisitionStrategy(
            id=f"github_search_{_slug(requirement)}",
            name=f"Search GitHub: {requirement}",
            source_type="github",
            source_url=github_url,
            description=f"Search GitHub for public Python repositories implementing '{requirement}'. Results reviewed before ingestion.",
            capabilities_provided=[requirement.lower()],
            estimated_minutes=10,
            success_probability=0.70,
            cost="Free",
            license="Varies (MIT/Apache preferred)",
            automation_level="Semi",
            compatibility={"*": "*"},
            risks=["License must be verified before ingestion", "Manual review required"],
            ranking_score=0.0,
            phase=1,
        ))
        return strategies

    def _strategy_docs(self, requirement: str, tokens: set) -> list:
        """Strategy: ingest public documentation pages related to the requirement."""
        strategies = []
        dcc_docs_map = {
            "unreal": ("unreal_docs", KNOWN_CAPABILITY_SOURCES["unreal_docs"]),
            "maya": ("maya_docs", KNOWN_CAPABILITY_SOURCES["maya_docs"]),
            "blender": ("blender_docs", KNOWN_CAPABILITY_SOURCES["blender_docs"]),
        }
        for dcc, (key, src) in dcc_docs_map.items():
            if dcc in tokens or any(t in src["provides"] for t in tokens):
                strategies.append(AcquisitionStrategy(
                    id=f"docs_{dcc}_{_slug(requirement)}",
                    name=src["name"],
                    source_type="docs",
                    source_url=src["url"],
                    description=src["description"],
                    capabilities_provided=src["provides"],
                    estimated_minutes=src["estimated_minutes"],
                    success_probability=src["success_probability"],
                    cost=src["cost"],
                    license=src["license"],
                    automation_level="Full",
                    compatibility=src["compatibility"],
                    risks=[],
                    ranking_score=0.0,
                    phase=1,
                ))
        return strategies

    def _strategy_from_catalog(self, requirement: str, tokens: set) -> list:
        """Match the requirement against the built-in known sources catalog."""
        strategies = []
        for key, src in KNOWN_CAPABILITY_SOURCES.items():
            provides = set(src.get("provides", []))
            if not (tokens & provides):
                continue
            strategies.append(AcquisitionStrategy(
                id=f"catalog_{key}_{_slug(requirement)}",
                name=src["name"],
                source_type=src["source_type"],
                source_url=src["url"],
                description=src["description"],
                capabilities_provided=src["provides"],
                estimated_minutes=src["estimated_minutes"],
                success_probability=src["success_probability"],
                cost=src["cost"],
                license=src["license"],
                automation_level=src["automation"],
                compatibility=src["compatibility"],
                risks=[] if src["cost"] == "Free" else ["Cost may apply"],
                ranking_score=0.0,
                phase=src["phase"],
            ))
        return strategies

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def rank_strategies(self, strategies: list) -> list:
        """Score each strategy: success × automation bonus + phase1 bonus − risk penalty − cost penalty."""
        automation_bonus = {"Full": 0.3, "Semi": 0.1, "Manual": 0.0}
        for s in strategies:
            score = s.success_probability
            score += automation_bonus.get(s.automation_level, 0.0)
            if s.phase == 1:
                score += 0.4
            if s.cost == "Free":
                score += 0.2
            score -= len(s.risks) * 0.05
            if s.license in {"Unknown", ""}:
                score -= 0.2
            s.ranking_score = round(score, 3)
        strategies.sort(key=lambda x: x.ranking_score, reverse=True)
        return strategies

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_strategy(
        self,
        strategy: AcquisitionStrategy,
        progress_cb: Optional[Callable] = None,
    ) -> AcquisitionResult:
        """Execute an approved acquisition strategy."""
        def _progress(msg: str, current: int = 0, total: int = 0) -> None:
            if progress_cb:
                try:
                    progress_cb(msg, current, total)
                except TypeError:
                    try:
                        progress_cb(msg)
                    except Exception:
                        pass
                except Exception:
                    pass

        try:
            if strategy.source_type == "github":
                return self._acquire_github(strategy, _progress)
            elif strategy.source_type == "docs":
                return self._acquire_docs(strategy, _progress)
            elif strategy.source_type == "codegen":
                return self._acquire_codegen(strategy, _progress)
            else:
                return self._acquire_manual(strategy, _progress)
        except Exception as exc:
            traceback.print_exc()
            return AcquisitionResult(
                strategy_id=strategy.id,
                success=False,
                message=f"Acquisition failed: {exc}",
                registered_capability_ids=[],
                local_path="",
            )

    def _acquire_github(self, strategy: AcquisitionStrategy, progress_cb: Callable) -> AcquisitionResult:
        """Phase 1: Download and ingest a public GitHub repository."""
        url = strategy.source_url
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.netloc.lower() in _ALLOWED_CODE_DOMAINS and parsed_url.path.rstrip("/") == "/search":
            progress_cb("GitHub search strategy requires selecting a reviewed repository before ingest.")
            return AcquisitionResult(
                strategy_id=strategy.id,
                success=True,
                message=(
                    "GitHub search is ready for review. Open the Web / GitHub Import flow, "
                    f"search with this candidate query, select a repository, then ingest it into pipeline tools:\n{url}"
                ),
                registered_capability_ids=[],
                local_path="",
            )
        if not is_allowed_code_url(url):
            return AcquisitionResult(
                strategy_id=strategy.id,
                success=False,
                message=f"URL blocked by ethics gate: only public github.com repositories are allowed. Got: {url}",
                registered_capability_ids=[],
                local_path="",
            )

        from tech_connector.services.github_ingest_service import parse_github_repo_reference, ingest_github_repo
        from tech_connector.services.tool_discovery_service import list_ingested_tools

        progress_cb(f"Parsing repository reference: {url}")
        ref = parse_github_repo_reference(url)
        target_dir = self._external_tools_dir / f"{ref.owner}__{ref.repo}"

        progress_cb(f"Downloading {ref.full_name}...")
        result = ingest_github_repo(ref, target_dir, progress_cb=progress_cb)
        if not result.get("ok"):
            return AcquisitionResult(
                strategy_id=strategy.id,
                success=False,
                message=result.get("error", "Unknown ingestion error"),
                registered_capability_ids=[],
                local_path=str(target_dir),
            )

        progress_cb("Indexing symbols...")
        actual_dir = Path(result.get("path") or target_dir)
        symbols = list_ingested_tools(actual_dir)
        entries = self._registry.register_ingested_tool(
            repo_name=ref.repo,
            repo_url=ref.clean_url,
            local_dir=actual_dir,
            symbols=symbols,
            notes=f"Phase 1 acquisition via capability planner.",
        )
        self._registry.save()

        registered_ids = [e.id for e in entries]
        progress_cb(f"Registered {len(registered_ids)} capabilities from {ref.repo}.")
        return AcquisitionResult(
            strategy_id=strategy.id,
            success=True,
            message=f"Ingested {ref.full_name}: {len(registered_ids)} capabilities registered.",
            registered_capability_ids=registered_ids,
            local_path=str(actual_dir),
        )

    def _acquire_docs(self, strategy: AcquisitionStrategy, progress_cb: Callable) -> AcquisitionResult:
        """Phase 1: Fetch and index public documentation pages."""
        url = strategy.source_url
        if not is_public_url(url):
            return AcquisitionResult(
                strategy_id=strategy.id,
                success=False,
                message=f"URL blocked by ethics gate: {url}",
                registered_capability_ids=[],
                local_path="",
            )

        progress_cb(f"Fetching documentation index: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AI-Studio/1.0"})
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req, timeout=10) as resp:
                content = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return AcquisitionResult(
                strategy_id=strategy.id,
                success=False,
                message=f"Could not fetch documentation: {exc}",
                registered_capability_ids=[],
                local_path="",
            )

        # Save to data/acquired/docs/
        docs_dir = self._project_root / "data" / "acquired" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        slug = _slug(strategy.name)
        doc_file = docs_dir / f"{slug}.html"
        doc_file.write_text(content, encoding="utf-8")

        # Register as a docs capability
        from tech_connector.services.capability_registry import CapabilityEntry, _utc_now
        entry = CapabilityEntry(
            id=f"docs_{slug}",
            name=strategy.name,
            category="docs",
            dcc_hosts=["*"],
            keywords=strategy.capabilities_provided,
            source="docs",
            file_path=str(doc_file),
            requires=[],
            acquired_at=_utc_now(),
            notes=f"Ingested from {url}.",
            import_module="",
            import_symbol="",
            phase=1,
            enabled=True,
        )
        self._registry.register(entry)
        self._registry.save()

        progress_cb(f"Documentation indexed: {doc_file.name}")
        return AcquisitionResult(
            strategy_id=strategy.id,
            success=True,
            message=f"Documentation ingested from {url}.",
            registered_capability_ids=[entry.id],
            local_path=str(doc_file),
        )

    def _acquire_codegen(self, strategy: AcquisitionStrategy, progress_cb: Callable) -> AcquisitionResult:
        """Phase 1: Generate an internal adapter/wrapper using the LLM."""
        progress_cb("Requesting internal code generation for missing capability...")
        # Signal to the caller that LLM codegen is needed — actual generation is handled upstream
        return AcquisitionResult(
            strategy_id=strategy.id,
            success=True,
            message=f"Codegen requested for: {strategy.name}. The LLM will generate the adapter.",
            registered_capability_ids=[],
            local_path="",
        )

    def _acquire_manual(self, strategy: AcquisitionStrategy, progress_cb: Callable) -> AcquisitionResult:
        """Phase 2: Return step-by-step instructions for manual acquisition."""
        steps = [
            f"1. Visit: {strategy.source_url}",
            f"2. {strategy.description}",
            "3. Download and import the asset/plugin into your project.",
            f"4. Once installed, re-run your original prompt — the capability will be detected automatically.",
        ]
        progress_cb("Generating manual acquisition instructions...")
        return AcquisitionResult(
            strategy_id=strategy.id,
            success=True,
            message="\n".join(steps),
            registered_capability_ids=[],
            local_path="",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_")[:48]


def format_strategy_summary(strategy: AcquisitionStrategy) -> str:
    """Format a strategy for display in the chat panel."""
    phase_label = "🤖 Phase 1 (Automated)" if strategy.phase == 1 else "🖱 Phase 2 (Requires action)"
    automation_icon = {"Full": "✅", "Semi": "⚡", "Manual": "🖐"}.get(strategy.automation_level, "")
    return (
        f"**{strategy.name}**  {phase_label}\n"
        f"  Cost: {strategy.cost} | License: {strategy.license} | "
        f"Success: {int(strategy.success_probability * 100)}% | "
        f"Automation: {automation_icon} {strategy.automation_level} | "
        f"~{strategy.estimated_minutes} min\n"
        f"  {strategy.description}"
    )
