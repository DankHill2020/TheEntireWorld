from __future__ import annotations

"""Critic-driven convergence policy for prompt-authored behavior contracts."""

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass
class BehaviorConvergenceAttempt:
    attempt: int
    strategy: str
    errors: list[str] = field(default_factory=list)
    uncovered_obligations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "strategy": self.strategy,
            "errors": list(self.errors),
            "uncovered_obligations": list(self.uncovered_obligations),
        }


class AdaptiveBehaviorConvergence:
    """Keep repairing until the critic accepts or grounded knowledge is required."""

    def __init__(self, max_attempts: int | None = None):
        parsed = int(max_attempts or 0)
        self.max_attempts = parsed if parsed > 0 else None
        self.attempts: list[BehaviorConvergenceAttempt] = []

    def strategy_for(self, attempt: int, validation: dict[str, Any] | None = None) -> str:
        errors = " ".join(str(value) for value in dict(validation or {}).get("errors") or []).lower()
        if attempt == 0:
            return "complete_contract"
        if "json" in errors or "expecting" in errors or "unterminated" in errors:
            return "schema_repair_from_scratch"
        if "coverage" in errors or "obligation" in errors:
            return "obligation_focused_recomposition"
        if "operation" in errors:
            return "atomic_operation_rewrite"
        if "input key" in errors:
            return "input_fidelity_rewrite"
        if attempt >= 4:
            return "minimal_semantic_reset"
        return "critic_guided_repair"

    def record(self, validation: dict[str, Any], strategy: str) -> None:
        self.attempts.append(
            BehaviorConvergenceAttempt(
                attempt=len(self.attempts) + 1,
                strategy=strategy,
                errors=[str(value) for value in validation.get("errors") or []],
                uncovered_obligations=[
                    str(value) for value in validation.get("uncovered_clauses") or []
                ],
            )
        )

    def repair_packet(
        self,
        base_packet: dict[str, Any],
        synthesis: dict[str, Any],
        validation: dict[str, Any],
        strategy: str,
    ) -> dict[str, Any]:
        packet = dict(base_packet)
        packet["repair_strategy"] = strategy
        packet["repair_attempt"] = len(self.attempts)
        packet["critic_errors"] = list(validation.get("errors") or [])
        packet["uncovered_obligations"] = list(validation.get("uncovered_clauses") or [])
        packet["instruction"] = (
            "Return a complete contract. Preserve accepted_fields exactly and regenerate only fields_to_regenerate. "
            "Continue until every critic error and behavior obligation is satisfied. Never claim success or omit an obligation."
        )
        accepted, regenerate = self._partition_behavior_fields(synthesis, validation)
        packet["repair_candidate"] = synthesis
        if accepted:
            packet["accepted_fields"] = accepted
        packet["fields_to_regenerate"] = regenerate
        packet["field_diagnostics"] = self._field_diagnostics(
            synthesis, validation, regenerate
        )
        packet["field_contracts"] = {
            "guards": (
                "array of complete predicate strings; each guard uses observed facts; numeric limits use "
                "within/at most/at least or an inequality only when the source supplies a number; otherwise use qualitative predicates"
            ),
            "observations": "array of measurable runtime facts that supply every guard input",
            "trigger": "one string such as 'G input is pressed'; retain requested keys and do not put guard conditions here",
            "operations": (
                "array of lowercase namespace.action strings including sensing plus an authoritative gameplay effect; "
                "movement requests must include movement.*, physics.*, character.*, or transform.*; no presentation work "
                "unless requested; describe reusable low-level effects, never perform/execute/initiate the whole behavior"
            ),
            "outcomes": "array of observable state or movement changes, never a tautological 'behavior performed' claim",
            "animation_roles": (
                "array of animation asset-purpose identifiers such as behavior_montage or locomotion_pose; "
                "never actor names such as player, target, or opponent"
            ),
            "proof_scenarios": (
                "array covering success, rejection, and any numeric boundary; the positive case names the observable outcome, "
                "never only 'behavior successful'"
            ),
            "clause_coverage": (
                "array of {source_clause, classification, covered_by}; classification is behavior/constraint/context "
                "and covered_by is an array of behavior IDs"
            ),
        }
        error_text = " ".join(str(value) for value in validation.get("errors") or []).lower()
        repair_hints: dict[str, str] = {}
        if "actor movement effect" in error_text:
            repair_hints["outcomes"] = (
                "State the character's requested physical movement explicitly using the source mechanic term and any observed direction."
            )
        if "actor movement assertion" in error_text:
            repair_hints["proof_scenarios"] = (
                "The positive scenario must assert the character's requested physical movement using the source mechanic term."
            )
        if "movement, physics" in error_text or "feature-level placeholder" in error_text:
            forbidden = [
                match.group(1)
                for match in re.finditer(
                    r"(?:placeholders?|effects):\s*([a-z][a-z0-9_.]+)",
                    error_text,
                )
            ]
            repair_hints["operations"] = (
                "Every operation named by the critic is forbidden and must disappear. For non-baseline traversal, "
                "use low-level effects such as physics.apply_directional_impulse and movement.apply_vertical_velocity; "
                "use movement.launch_toward_observed_point for target-directed travel. Do not repeat the mechanic name."
                + (" Forbidden exact keys: " + ", ".join(forbidden) if forbidden else "")
            )
        if "operations omit required source behavior semantics" in error_text:
            repair_hints["operations"] = (
                "Use reusable low-level effects whose action retains the relevant source mechanic term, "
                "for example movement.apply_<source_effect>_impulse. The action must start with a concrete "
                "verb such as apply/set/start and must not name the entire behavior as a placeholder."
            )
        if "operations introduce effects not grounded" in error_text:
            ungrounded = sorted(
                set(
                    re.findall(
                        r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*",
                        " ".join(str(value) for value in validation.get("errors") or []),
                    )
                )
            )
            repair_hints["operations"] = (
                "Remove effects whose concepts are absent from the source clause and observations. Keep only source-grounded atomic effects."
                + (" Forbidden exact operation keys: " + ", ".join(ungrounded) if ungrounded else "")
            )
        if "outcomes introduce effects not grounded" in error_text:
            repair_hints["outcomes"] = (
                "Remove outcome concepts absent from the source clause and observations. Describe only the requested observable change."
            )
        if "observable state or movement change" in error_text:
            repair_hints["outcomes"] = (
                "Name the physical change, for example: character launches away from the observed surface and gains upward velocity."
            )
        if "invented numeric constants" in error_text:
            repair_hints["numeric_values"] = (
                "Delete every numeric value absent from the source. Unknown tuning values belong in ambiguities, never assumptions."
            )
        if "surface-relative movement" in error_text:
            repair_hints["surface_basis"] = (
                "Observe the measured surface normal/direction, use it as the basis for a directional movement or physics effect, "
                "and state that the character moves away from or along that measured surface basis."
            )
        if "guards do not enforce a source-clause precondition" in error_text:
            repair_hints["guards"] = (
                "Include a qualitative guard using exact mechanic/context terms from source_clauses. "
                "Do not introduce nouns or conditions absent from the source and locked observations."
            )
        if "observations omit source-clause precondition facts" in error_text:
            repair_hints["observations"] = (
                "Observe the condition explicitly named after while/when/if/after in the source clause."
            )
        if "unsupported kinematic precondition" in error_text:
            repair_hints["guards"] = (
                "Remove speed, velocity, and momentum requirements absent from the source; retain only requested context and measured validity."
            )
        if "unsupported symbolic tuning threshold" in error_text:
            repair_hints["guards"] = (
                "Remove named thresholds or tuning variables absent from the source. Test the observed source state directly."
            )
        if "observations omit the requested distance measurement" in error_text:
            repair_hints["observations"] = (
                "Add a measured distance or range fact for the exact source-authored limit."
            )
        if "guards omit the requested distance limit" in error_text:
            repair_hints["guards"] = (
                "Enforce the exact source-authored distance with within/at most or <=, preserving any other valid guard."
            )
        if "target-directed travel" in error_text:
            repair_hints["operations"] = (
                "Use a target-directed movement effect such as movement.launch_toward_observed_hit; preserve required sensing operations."
            )
            repair_hints["outcomes"] = (
                "State that the character moves toward the measured hit point."
            )
        if "hit-gated sensing operation" in error_text:
            repair_hints["operations"] = (
                "Preserve existing valid movement effects and add a reusable collision/trace/query operation that produces the measured hit."
            )
        if "directional movement basis" in error_text:
            repair_hints["observations"] = "Observe the requested input or movement direction."
            repair_hints["operations"] = "Apply movement using the observed direction."
            repair_hints["outcomes"] = "State that the character moves along the observed direction."
        if "bounded invulnerability implementation" in error_text:
            repair_hints["operations"] = (
                "Add explicit enable-window and scheduled-clear invulnerability operations; preserve directional movement."
            )
            repair_hints["outcomes"] = (
                "State that invulnerability is active only during the bounded window."
            )
        if "circular invulnerability precondition" in error_text or "unsupported hit precondition" in error_text:
            repair_hints["guards"] = (
                "Remove effect-state and unrelated hit guards. Use a source-grounded activation-availability predicate."
            )
        if "negative proof for the requested precondition" in error_text:
            repair_hints["proof_scenarios"] = (
                "Add a rejection case where the requested source precondition is false and authoritative state remains unchanged."
            )
        if "wall-jump outcome" in error_text:
            repair_hints["outcomes"] = (
                "State explicitly: character moves away from the measured wall normal and gains upward movement."
            )
        if "vertical surface normal" in error_text:
            repair_hints["guards"] = (
                "A vertical wall does not have a vertical normal. Require a valid measured wall normal without inventing orientation tolerances."
            )
        if "input activation event" in error_text or "omits requested input keys" in error_text:
            repair_hints["trigger"] = "Use one string in the form: <requested key> input is pressed."
        if "actors rather than animation asset roles" in error_text or "do not identify the source behavior" in error_text:
            repair_hints["animation_roles"] = (
                "Replace actor names with one behavior-specific asset role, for example grapple_montage."
            )
        if repair_hints:
            packet["repair_hints"] = repair_hints
        return packet

    @staticmethod
    def _field_diagnostics(
        synthesis: dict[str, Any], validation: dict[str, Any], fields: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Describe rejected list members separately when critic evidence is exact."""

        diagnostics: dict[str, dict[str, Any]] = {}
        errors = [str(value) for value in validation.get("errors") or []]
        for path in fields:
            match = re.fullmatch(r"behaviors\[(\d+)\]\.([a-z_]+)", path)
            if not match:
                diagnostics[path] = {"status": "rejected", "errors": errors}
                continue
            index, field_name = int(match.group(1)), match.group(2)
            behaviors = list(dict(synthesis or {}).get("behaviors") or [])
            behavior = dict(behaviors[index] or {}) if index < len(behaviors) else {}
            value = behavior.get(field_name)
            field_errors = [
                error for error in errors
                if re.search(rf"behavior_{index + 1}\b", error, re.I)
                and re.search(rf"\b{re.escape(field_name)}\b", error, re.I)
            ]
            row: dict[str, Any] = {"status": "rejected", "errors": field_errors or errors}
            if isinstance(value, list):
                named = set(
                    re.findall(
                        r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*",
                        " ".join(field_errors),
                    )
                )
                rejected_items = [item for item in value if str(item) in named]
                accepted_items = [item for item in value if item not in rejected_items]
                if rejected_items and accepted_items:
                    row.update(
                        status="partially_rejected",
                        accepted_items=accepted_items,
                        rejected_items=rejected_items,
                    )
            diagnostics[path] = row
        return diagnostics

    @staticmethod
    def _partition_behavior_fields(
        synthesis: dict[str, Any], validation: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        errors = [str(value) for value in validation.get("errors") or []]
        synthesis_behaviors = list(dict(synthesis or {}).get("behaviors") or [])
        field_names = (
            "id", "title", "source_clauses", "trigger", "observations", "guards", "outcomes",
            "animation_roles", "proof_scenarios", "operations",
        )
        invalid: dict[int, set[str]] = {}
        regenerate: list[str] = []
        regenerate_coverage = False
        for error in errors:
            if error.lower().startswith("coverage_"):
                regenerate_coverage = True
                regenerate.append("clause_coverage")
                continue
            match = re.search(r"behavior_(\d+)", error)
            indexes = (
                [int(match.group(1)) - 1]
                if match
                else list(range(len(synthesis_behaviors)))
            )
            fields = set()
            lowered = error.lower()
            primary_match = re.search(
                r"behavior_\d+\s+(?:field\s+)?([a-z_]+)", lowered
            )
            primary_field = primary_match.group(1) if primary_match else ""
            if primary_field in field_names:
                fields.add(primary_field)
            elif "surface-relative movement omits a measured surface direction or normal" in lowered:
                fields.add("observations")
            elif "surface-relative movement outcome" in lowered or "wall-jump outcome" in lowered:
                fields.add("outcomes")
            else:
                for field_name in field_names:
                    readable = field_name.replace("_", " ")
                    if re.search(
                        rf"(?<![a-z0-9_])(?:{re.escape(field_name)}|{re.escape(readable)})(?![a-z0-9_])",
                        lowered,
                    ):
                        fields.add(field_name)
            if "input key" in lowered:
                fields.add("trigger")
            if "uncovered obligation" in lowered or "missing obligation" in lowered:
                fields.add("source_clauses")
            if not fields:
                fields.update(field_names)
            for index in indexes:
                invalid.setdefault(index, set()).update(fields)
                regenerate.extend(
                    f"behaviors[{index}].{field_name}"
                    for field_name in sorted(fields)
                )

        accepted_behaviors = []
        for index, behavior in enumerate(synthesis_behaviors):
            behavior = dict(behavior or {})
            rejected = invalid.get(index, set())
            accepted_behavior = {
                field_name: behavior[field_name]
                for field_name in field_names
                if field_name not in rejected and field_name in behavior
            }
            # Preserve behavior indexes even when every field in one item needs repair.
            accepted_behaviors.append(accepted_behavior)
        accepted: dict[str, Any] = {}
        if accepted_behaviors:
            accepted["behaviors"] = accepted_behaviors
        if not regenerate_coverage and not any("obligation" in error.lower() for error in errors):
            accepted["clause_coverage"] = list(dict(synthesis or {}).get("clause_coverage") or [])
        return accepted, list(dict.fromkeys(regenerate))

    def accepted(self, validation: dict[str, Any]) -> bool:
        return bool(validation.get("ok"))

    def can_continue(self) -> bool:
        return self.max_attempts is None or len(self.attempts) < self.max_attempts

    def trace(self) -> list[dict[str, Any]]:
        return [attempt.to_dict() for attempt in self.attempts]
