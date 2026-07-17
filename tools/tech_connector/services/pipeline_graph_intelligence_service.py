"""Advisory intelligence for pipeline node graph edits.

This service is intentionally side-effect free. It turns a graph snapshot and
validation issues into troubleshooting guidance, repair candidates, and a
visible edit lifecycle. The node view and prompt router can consume this
without creating a second execution path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PIPELINE_GRAPH_LIFECYCLE = (
    "REQUEST_RECEIVED",
    "GRAPH_SNAPSHOT_CAPTURED",
    "INTENT_AND_CONTEXT_INFERRED",
    "DATA_FLOW_ANALYZED",
    "REPAIR_OR_EXTENSION_PLANNED",
    "AWAITING_APPROVAL_IF_MUTATING",
    "GRAPH_MUTATION_APPLIED",
    "PYTHON_REGENERATED",
    "VALIDATED",
    "REPORTED",
)

PIPELINE_GRAPH_FAILURE_STATES = (
    "BLOCKED_MISSING_REQUIRED_INPUT",
    "BLOCKED_BROKEN_CONNECTION",
    "BLOCKED_AMBIGUOUS_CONTEXT",
    "BLOCKED_TYPE_MISMATCH",
    "FLOW_CYCLE_DETECTED",
    "PYTHON_GENERATION_FAILED",
    "VALIDATION_FAILED",
)

PIPELINE_GRAPH_LAYOUT_CONTRACT = (
    "Keep primary execution flow readable left-to-right unless existing layout clearly differs.",
    "Place setup/context nodes before the consumer node they satisfy.",
    "Keep utility conversion nodes close to the connection they adapt.",
    "Avoid overlapping nodes and avoid long crossing data links when a closer compatible producer exists.",
    "Group DCC/engine/VCS/messaging domains in visible clusters when the pipeline spans tools.",
)


@dataclass(frozen=True)
class PipelineGraphIssue:
    severity: str
    category: str
    step_id: str
    node: str
    port: str
    message: str
    likely_cause: str
    suggested_actions: tuple[str, ...] = ()
    blocks_compile: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "step_id": self.step_id,
            "node": self.node,
            "port": self.port,
            "message": self.message,
            "likely_cause": self.likely_cause,
            "suggested_actions": list(self.suggested_actions),
            "blocks_compile": self.blocks_compile,
        }


@dataclass(frozen=True)
class PipelineGraphAnalysis:
    status: str
    summary: str
    lifecycle: tuple[str, ...] = PIPELINE_GRAPH_LIFECYCLE
    failure_states: tuple[str, ...] = PIPELINE_GRAPH_FAILURE_STATES
    layout_contract: tuple[str, ...] = PIPELINE_GRAPH_LAYOUT_CONTRACT
    graph_facts: dict[str, Any] = field(default_factory=dict)
    issues: tuple[PipelineGraphIssue, ...] = ()
    next_actions: tuple[str, ...] = ()
    repair_candidates: tuple[dict[str, Any], ...] = ()
    troubleshooting_path: tuple[str, ...] = ()
    validation_gates: tuple[str, ...] = ()
    confidence_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": "pipeline_graph_intelligence_v1",
            "status": self.status,
            "summary": self.summary,
            "lifecycle": list(self.lifecycle),
            "failure_states": list(self.failure_states),
            "layout_contract": list(self.layout_contract),
            "graph_facts": dict(self.graph_facts),
            "issues": [issue.to_dict() for issue in self.issues],
            "next_actions": list(self.next_actions),
            "repair_candidates": list(self.repair_candidates),
            "troubleshooting_path": list(self.troubleshooting_path),
            "validation_gates": list(self.validation_gates),
            "confidence_notes": list(self.confidence_notes),
        }


def analyze_pipeline_graph(
    snapshot: dict[str, Any],
    validation_issues: list[dict[str, Any]] | None = None,
    *,
    prompt: str = "",
) -> dict[str, Any]:
    """Build a structured advisory report for a pipeline graph."""
    issues = tuple(_classify_issue(issue) for issue in (validation_issues or []))
    graph_facts = _graph_facts(snapshot)
    repair_candidates = tuple(_repair_candidates(snapshot, issues))
    status = "ready" if not issues else ("blocked" if any(issue.blocks_compile for issue in issues) else "warning")
    summary = _summary(status, graph_facts, issues)
    analysis = PipelineGraphAnalysis(
        status=status,
        summary=summary,
        graph_facts=graph_facts,
        issues=issues,
        next_actions=tuple(_next_actions(status, issues, repair_candidates)),
        repair_candidates=repair_candidates,
        troubleshooting_path=tuple(_troubleshooting_path(issues, prompt=prompt)),
        validation_gates=tuple(_validation_gates(snapshot, issues)),
        confidence_notes=tuple(_confidence_notes(snapshot, issues)),
    )
    return analysis.to_dict()


def graph_snapshot_from_view(view: Any) -> dict[str, Any]:
    """Extract a graph snapshot from PipelineNodeView without mutating it."""
    nodes = []
    ordered_ids = []
    try:
        ordered_ids = list(view.execution_order())
    except Exception:
        ordered_ids = list(getattr(view, "nodes", {}).keys())
    for step_id in ordered_ids:
        node = getattr(view, "nodes", {}).get(step_id)
        if not node:
            continue
        symbol = getattr(node, "symbol", {}) or {}
        nodes.append(
            {
                "step_id": step_id,
                "name": str(symbol.get("name") or step_id),
                "provider": str(symbol.get("provider_id") or symbol.get("provider") or ""),
                "params": list(getattr(node, "params", []) or []),
                "outputs": list(getattr(node, "outputs", []) or []),
                "x": float(getattr(node, "x", 0) or 0),
                "y": float(getattr(node, "y", 0) or 0),
            }
        )
    links = []
    for link in list(getattr(view, "links", []) or []):
        links.append(
            {
                "from_step": getattr(link, "from_step", ""),
                "from_output": getattr(link, "from_output", ""),
                "to_step": getattr(link, "to_step", ""),
                "to_input": getattr(link, "to_input", ""),
                "type": getattr(link, "link_type", ""),
            }
        )
    return {"nodes": nodes, "links": links, "ordered_step_ids": ordered_ids}


def compact_pipeline_graph_report(analysis: dict[str, Any], *, max_issues: int = 4) -> str:
    if not analysis:
        return ""
    lines = [analysis.get("summary") or "Pipeline graph analyzed."]
    for issue in list(analysis.get("issues") or [])[:max_issues]:
        lines.append(f"- {issue.get('message')} Next: {'; '.join(issue.get('suggested_actions') or [])}")
    remaining = len(analysis.get("issues") or []) - max_issues
    if remaining > 0:
        lines.append(f"- {remaining} more issue(s).")
    next_actions = analysis.get("next_actions") or []
    if next_actions:
        lines.append("Next actions: " + "; ".join(str(item) for item in next_actions[:4]))
    return "\n".join(lines)


def _classify_issue(issue: dict[str, Any]) -> PipelineGraphIssue:
    message = str(issue.get("message") or "")
    step_id = str(issue.get("step_id") or "")
    node = str(issue.get("node") or "Unknown node")
    port = str(issue.get("input") or issue.get("port") or "")
    lower = message.lower()
    if "missing node" in lower:
        return PipelineGraphIssue(
            severity="error",
            category="broken_connection",
            step_id=step_id,
            node=node,
            port=port,
            message=message,
            likely_cause="The graph changed after this link was created, or a referenced node was deleted.",
            suggested_actions=("Delete the stale link.", "Reconnect to an existing node/output.", "Use Undo Graph Change if this just happened."),
        )
    if "missing output" in lower:
        return PipelineGraphIssue(
            severity="error",
            category="missing_output",
            step_id=step_id,
            node=node,
            port=port,
            message=message,
            likely_cause="The source function no longer exposes that output, or the output metadata changed.",
            suggested_actions=("Refresh/rebuild the source node metadata.", "Reconnect to an available output.", "Add a utility adapter node if the return shape changed."),
        )
    if "missing input" in lower or "targets missing" in lower:
        return PipelineGraphIssue(
            severity="error",
            category="missing_input",
            step_id=step_id,
            node=node,
            port=port,
            message=message,
            likely_cause="The target function signature changed or the link points to an old parameter name.",
            suggested_actions=("Refresh/rebuild the target node metadata.", "Reconnect to a current input.", "Move the value into a literal input if it is no longer data-driven."),
        )
    if "needs a value or data connection" in lower:
        return PipelineGraphIssue(
            severity="error",
            category="unfilled_required_input",
            step_id=step_id,
            node=node,
            port=port,
            message=message,
            likely_cause="A required parameter has no literal value, default value, or incoming data link.",
            suggested_actions=("Use Add and Connect Context to add likely producer nodes.", "Connect a compatible existing output.", "Enter a literal value in Node Attributes."),
        )
    return PipelineGraphIssue(
        severity="warning",
        category="validation",
        step_id=step_id,
        node=node,
        port=port,
        message=message,
        likely_cause="The graph validator found an issue that needs inspection.",
        suggested_actions=("Inspect the highlighted node.", "Re-run graph validation after repair."),
        blocks_compile=True,
    )


def _graph_facts(snapshot: dict[str, Any]) -> dict[str, Any]:
    nodes = list(snapshot.get("nodes") or [])
    links = list(snapshot.get("links") or [])
    providers = sorted({str(node.get("provider") or "project") for node in nodes})
    return {
        "node_count": len(nodes),
        "link_count": len(links),
        "data_link_count": len([link for link in links if link.get("type") == "data"]),
        "flow_link_count": len([link for link in links if link.get("type") == "flow"]),
        "providers": providers,
        "has_cross_domain_flow": len([p for p in providers if p]) > 1,
    }


def _summary(status: str, graph_facts: dict[str, Any], issues: tuple[PipelineGraphIssue, ...]) -> str:
    node_count = int(graph_facts.get("node_count") or 0)
    link_count = int(graph_facts.get("link_count") or 0)
    if status == "ready":
        return f"Pipeline graph ready: {node_count} node(s), {link_count} link(s), no blocking data-flow issues."
    blocking = len([issue for issue in issues if issue.blocks_compile])
    return f"Pipeline graph blocked: {blocking} blocking issue(s) across {node_count} node(s)."


def _repair_candidates(snapshot: dict[str, Any], issues: tuple[PipelineGraphIssue, ...]) -> list[dict[str, Any]]:
    nodes = list(snapshot.get("nodes") or [])
    outputs = []
    for node in nodes:
        for output in node.get("outputs") or []:
            outputs.append(
                {
                    "step_id": node.get("step_id"),
                    "node": node.get("name"),
                    "output": output.get("name"),
                    "python_type": output.get("python_type") or output.get("annotation") or output.get("type") or "",
                    "semantic_type": output.get("semantic_type") or "",
                }
            )
    candidates: list[dict[str, Any]] = []
    for issue in issues:
        if issue.category != "unfilled_required_input":
            continue
        port_l = issue.port.lower()
        for output in outputs:
            output_name = str(output.get("output") or "")
            if output_name.lower() == port_l or port_l in output_name.lower():
                candidates.append(
                    {
                        "issue": issue.message,
                        "action": "connect_existing_output",
                        "from": f"{output.get('node')}.{output_name}",
                        "to": f"{issue.node}.{issue.port}",
                        "confidence": "medium" if output_name.lower() != port_l else "high",
                        "evidence": "Output name appears compatible with missing required input.",
                    }
                )
                break
        candidates.append(
            {
                "issue": issue.message,
                "action": "fill_literal_or_add_context",
                "to": f"{issue.node}.{issue.port}",
                "confidence": "medium",
                "evidence": "Required input has no data producer in the current graph.",
            }
        )
    return candidates[:12]


def _next_actions(status: str, issues: tuple[PipelineGraphIssue, ...], repair_candidates: tuple[dict[str, Any], ...]) -> list[str]:
    if status == "ready":
        return ["Compile/save the pipeline.", "Run a focused test before using it in production."]
    actions = []
    if any(issue.category == "unfilled_required_input" for issue in issues):
        actions.append("Resolve required inputs before compile/save/run.")
    if any(issue.category in {"broken_connection", "missing_output", "missing_input"} for issue in issues):
        actions.append("Repair stale links or rebuild affected node metadata.")
    if repair_candidates:
        actions.append("Review repair candidates and apply the smallest reversible graph change.")
    actions.append("Refresh validation after each repair; do not run until the status is ready or explicitly accepted.")
    return actions


def _troubleshooting_path(issues: tuple[PipelineGraphIssue, ...], *, prompt: str = "") -> list[str]:
    if not issues:
        return [
            "Confirm the generated Python matches the current graph order and links.",
            "Run compile/save validation.",
            "Run the smallest available test or dry-run path.",
        ]
    return [
        "Start with broken/stale links before filling values; stale links can hide the true required inputs.",
        "For each highlighted node, decide whether the input should be literal, connected from existing context, or produced by a new setup node.",
        "Prefer Add and Connect Existing Context when the graph already has compatible outputs.",
        "Prefer Add and Connect Context when registered predecessor functions exist.",
        "Use Undo Graph Change if the issue appeared immediately after a graph mutation.",
    ]


def _validation_gates(snapshot: dict[str, Any], issues: tuple[PipelineGraphIssue, ...]) -> list[str]:
    gates = [
        "No required input is missing a literal value, default, or incoming data link.",
        "Every data link references an existing output and input.",
        "Every flow link references existing nodes and the graph has no flow cycle.",
        "Generated Python is regenerated from the current graph snapshot.",
    ]
    if (snapshot.get("links") or []):
        gates.append("Connection repair was validated after link edits.")
    if issues:
        gates.append("Previously reported issues are cleared or explicitly accepted with risk.")
    return gates


def _confidence_notes(snapshot: dict[str, Any], issues: tuple[PipelineGraphIssue, ...]) -> list[str]:
    notes = []
    if not snapshot.get("nodes"):
        notes.append("No graph nodes were present; guidance is limited.")
    if issues:
        notes.append("Graph is not ready for execution until blocking issues are resolved.")
    else:
        notes.append("No data-flow issues were found by static graph validation.")
    return notes
