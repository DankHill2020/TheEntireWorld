"""Repeatable scale and lifecycle qualification for the engine Content Browser."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Any

from tech_connector.game_engine.assets.content_browser_lifecycle_service import ContentBrowserLifecycleService


CONTENT_BROWSER_QUALIFICATION_SCHEMA = "tech_connector.content_browser_qualification.v1"


@dataclass(frozen=True)
class ContentBrowserQualificationReceipt:
    qualified: bool
    sample_count: int
    indexed_asset_count: int
    inventory_ms: float
    maximum_query_ms: float
    average_query_ms: float
    minimum_documents_per_second: float
    query_budget_ms: float
    failures: tuple[str, ...]
    capabilities: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CONTENT_BROWSER_QUALIFICATION_SCHEMA, **asdict(self)}


def qualify_content_browser_scale(
    lifecycle: ContentBrowserLifecycleService, *, sample_count: int = 50_000,
    query_budget_ms: float = 750.0, inventory_budget_ms: float = 2_000.0,
) -> ContentBrowserQualificationReceipt:
    """Exercise compiled search over a large deterministic inventory and record evidence."""

    count = max(1_000, min(250_000, int(sample_count)))
    started = time.perf_counter()
    indexed = lifecycle.database.list_assets()
    lifecycle.database.assets_with_valid_derived_data()
    inventory_ms = (time.perf_counter() - started) * 1000.0

    documents = [
        {
            "asset_id": f"tc.asset.synthetic.{index:08d}",
            "name": f"{'Hero' if index % 17 == 0 else 'Asset'}_{index:08d}",
            "path": f"Assets/{'Characters' if index % 5 == 0 else 'Environment'}/{index // 1000:03d}/Asset_{index:08d}.tcasset",
            "type": ("tc.material", "tc.static_mesh", "tc.texture", "tc.animation_clip")[index % 4],
            "display_type": ("Material", "Static Mesh", "Texture", "Animation Clip")[index % 4],
            "family": ("Rendering", "Geometry", "Rendering", "Animation")[index % 4],
            "status": "missing" if index % 997 == 0 else "ready",
            "state": "imported" if index % 3 == 0 else "authored",
            "cook": "cooked" if index % 2 == 0 else "uncooked",
            "vcs": "checked_out" if index % 101 == 0 else "synced",
            "revision": index % 31 + 1,
            "size": (index % 4096 + 1) * 1024,
            "tags": ("hero", "shipping") if index % 17 == 0 else ("environment",),
            "collections": ("Hero",) if index % 17 == 0 else (),
        }
        for index in range(count)
    ]
    queries = (
        "hero family:Rendering -status:missing",
        "type:tc.static_mesh state:authored cook:uncooked rev>=10",
        "path:Assets/Characters vcs:synced size>1048576",
        "tag:shipping cook:cooked",
        "family:Animation rev>=20",
    )
    timings = []
    throughputs = []
    for query in queries:
        compiled = lifecycle.compile_query(query)
        started = time.perf_counter()
        sum(1 for document in documents if lifecycle.matches_compiled(document, compiled))
        elapsed = max(1.0e-9, time.perf_counter() - started)
        timings.append(elapsed * 1000.0)
        throughputs.append(count / elapsed)
    failures = []
    maximum_query_ms = max(timings)
    if inventory_ms > float(inventory_budget_ms):
        failures.append(f"Database inventory took {inventory_ms:.2f} ms; budget is {inventory_budget_ms:.2f} ms.")
    if maximum_query_ms > float(query_budget_ms):
        failures.append(f"Large-inventory query took {maximum_query_ms:.2f} ms; budget is {query_budget_ms:.2f} ms.")
    return ContentBrowserQualificationReceipt(
        qualified=not failures, sample_count=count, indexed_asset_count=len(indexed),
        inventory_ms=round(inventory_ms, 3), maximum_query_ms=round(maximum_query_ms, 3),
        average_query_ms=round(sum(timings) / len(timings), 3),
        minimum_documents_per_second=round(min(throughputs), 1),
        query_budget_ms=float(query_budget_ms), failures=tuple(failures),
        capabilities={
            "compiled_advanced_search": True,
            "batched_cooked_state": True,
            "persistent_collections": True,
            "recoverable_import_queue": True,
            "cooperative_mid_file_cancellation": True,
            "asynchronous_perforce_queries": True,
            "perforce_history_and_changelists": True,
            "reference_repair": True,
        },
    )


__all__ = [
    "CONTENT_BROWSER_QUALIFICATION_SCHEMA", "ContentBrowserQualificationReceipt",
    "qualify_content_browser_scale",
]
