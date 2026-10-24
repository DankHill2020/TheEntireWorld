"""Measure the source-backed nested scan in Unreal graph patch validation."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import time

from tech_connector.services.unreal.graph_patch_service import (
    GraphPatch,
    GraphPatchOperation,
    _validate_added_nodes_in_snapshot,
)


SOURCE = Path(__file__).resolve().parents[1] / "services" / "unreal" / "graph_patch_service.py"


class CountedNode(dict):
    name_reads = 0

    def get(self, key, default=None):
        if key == "name":
            CountedNode.name_reads += 1
        return super().get(key, default)


def measure(add_operations: int, nodes: int) -> dict:
    patch = GraphPatch(
        patch_id="review-proof", target_asset="/Game/Review", target_graph="EventGraph",
        operations=[GraphPatchOperation(
            op="add_node", graph="EventGraph", node=f"Missing_{index}",
        ) for index in range(add_operations)],
    )
    snapshot = {"name": "EventGraph", "nodes": [
        CountedNode(name=f"Node_{index}", **{"class": "K2Node_CallFunction"})
        for index in range(nodes)
    ]}
    timings = []
    counts = []
    for _ in range(5):
        CountedNode.name_reads = 0
        started = time.perf_counter()
        errors = _validate_added_nodes_in_snapshot(patch, snapshot)
        timings.append(time.perf_counter() - started)
        counts.append(CountedNode.name_reads)
        assert len(errors) == add_operations
    assert counts == [add_operations * nodes] * 5
    return {"add_operations": add_operations, "nodes": nodes,
            "node_name_reads": counts[0], "median_seconds": round(median(timings), 6)}


def main() -> int:
    output_root = Path(os.environ["TC_REVIEW_PROOF_ROOT"]).resolve()
    suffix = os.environ.get("TC_REVIEW_PROOF_SUFFIX", "v1")
    if not suffix.isidentifier():
        raise ValueError("TC_REVIEW_PROOF_SUFFIX must be a simple identifier")
    output = output_root / f"unreal_graph_patch_review_{suffix}.json"
    if output.exists():
        raise FileExistsError(output)
    source_before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    target = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_validate_added_nodes_in_snapshot")
    outer = next(node for node in ast.walk(target) if isinstance(node, ast.For)
                 and isinstance(node.iter, ast.Attribute)
                 and node.iter.attr == "operations")
    inner = next(node for statement in outer.body for node in ast.walk(statement)
                 if isinstance(node, ast.For) and isinstance(node.iter, ast.Name)
                 and node.iter.id == "graph_nodes")
    rows = [measure(12, 40), measure(12, 80), measure(24, 80)]
    source_after = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert source_before == source_after
    assert [row["node_name_reads"] for row in rows] == [480, 960, 1920]
    report = {
        "schema": "tech_connector.unreal_graph_patch_review.v1",
        "source": str(SOURCE), "source_sha256": source_after,
        "source_unchanged": True,
        "finding": "add-node validation rescans all graph nodes per add operation",
        "outer_line": outer.lineno, "inner_line": inner.lineno,
        "samples": rows,
        "scope": "synthetic Python snapshot; not a live Unreal latency measurement",
        "ok": True,
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output), "samples": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
