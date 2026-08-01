"""Small default reasoning layers that remain domain-neutral."""

from __future__ import annotations

from reasoning_runtime.reasoning.layers import (
    ReasoningFrame,
    ReasoningLayer,
    ReasoningLayerResult,
)


class RequestFramingLayer(ReasoningLayer):
    name = "request_framing"

    def run(self, frame: ReasoningFrame) -> ReasoningLayerResult:
        text = " ".join(str(frame.request or "").split())
        understanding = {
            **frame.understanding,
            "normalized_request": text,
            "is_empty": not bool(text),
        }
        return ReasoningLayerResult(
            frame=frame.with_updates(understanding=understanding),
            ok=bool(text),
            diagnostics=() if text else ("Request is empty.",),
        )


class GapDetectionLayer(ReasoningLayer):
    name = "gap_detection"

    def run(self, frame: ReasoningFrame) -> ReasoningLayerResult:
        gaps = list(frame.gaps)
        if "?" in frame.request and not frame.evidence:
            gaps.append(
                {
                    "key": "supporting_evidence",
                    "kind": "knowledge",
                    "question": "What evidence is needed to answer or act safely?",
                }
            )
        return ReasoningLayerResult(frame=frame.with_updates(gaps=tuple(gaps)))


class PlanSketchLayer(ReasoningLayer):
    name = "plan_sketch"

    def run(self, frame: ReasoningFrame) -> ReasoningLayerResult:
        if frame.plan:
            return ReasoningLayerResult(frame=frame)
        plan = {
            "goal": frame.understanding.get("normalized_request") or frame.request,
            "steps": [],
            "requires_domain_planner": True,
        }
        return ReasoningLayerResult(frame=frame.with_updates(plan=plan))
