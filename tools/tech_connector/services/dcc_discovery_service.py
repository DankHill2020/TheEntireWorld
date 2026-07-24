# coding=utf-8
"""
DCC Discovery & Context Exploration Service for Tech Connector.

Mimics the deep exploration, blueprint loading, and stub searching
behaviors of advanced Unreal Engine AI tools (like Ludus AI).
"""

from contextlib import closing
from typing import Any, Callable

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.engine.progress_events import ActivityEvent, ProgressEvent

ProgressCallback = Callable[[ProgressEvent], None]
ActivityCallback = Callable[[ActivityEvent], None]

class DCCDiscoveryService:
    """Explores the active Unreal project context and APIs before executing actions."""

    def __init__(self, bridge: UnrealBridge | None = None):
        self.bridge = bridge or UnrealBridge()

    def query_knowledge_symbols(self, query_terms: list[str]) -> list[dict[str, Any]]:
        """Queries local sqlite database or fallback map for symbols matching query terms."""
        # High-fidelity fallback Unreal API signatures
        fallback_unreal_symbols = {
            "skeletalmeshcomponent": [
                {
                    "kind": "property",
                    "qualname": "unreal.SkeletalMeshComponent.anim_class",
                    "signature": "anim_class: Class",
                    "docstring": "The Anim Blueprints class to run on this component."
                },
                {
                    "kind": "method",
                    "qualname": "unreal.SkeletalMeshComponent.get_anim_instance()",
                    "signature": "get_anim_instance() -> AnimInstance",
                    "docstring": "Returns the active AnimInstance executing on the mesh."
                }
            ],
            "animinstance": [
                {
                    "kind": "method",
                    "qualname": "unreal.AnimInstance.montage_play(montage, play_rate=1.0)",
                    "signature": "montage_play(montage: AnimMontage, play_rate: float) -> float",
                    "docstring": "Plays an animation montage."
                },
                {
                    "kind": "method",
                    "qualname": "unreal.AnimInstance.get_active_montage()",
                    "signature": "get_active_montage() -> AnimMontage",
                    "docstring": "Returns the currently active montage."
                }
            ],
            "get_default_object": [
                {
                    "kind": "function",
                    "qualname": "unreal.get_default_object(class_object)",
                    "signature": "get_default_object(class_object: Class) -> Object",
                    "docstring": "Returns the Class Default Object (CDO) for the specified class."
                }
            ],
            "load_asset": [
                {
                    "kind": "function",
                    "qualname": "unreal.EditorAssetLibrary.load_blueprint_class(asset_path)",
                    "signature": "load_blueprint_class(asset_path: str) -> Class",
                    "docstring": "Loads the generated class of a Blueprint asset."
                }
            ],
            "charactermovement": [
                {
                    "kind": "property",
                    "qualname": "unreal.CharacterMovementComponent.movement_mode",
                    "signature": "movement_mode: MovementMode",
                    "docstring": "The active movement mode (e.g. MOVE_Walking, MOVE_Flying)."
                },
                {
                    "kind": "method",
                    "qualname": "unreal.CharacterMovementComponent.set_movement_mode(new_mode)",
                    "signature": "set_movement_mode(new_mode: MovementMode) -> None",
                    "docstring": "Changes the active movement mode of the character."
                }
            ],
            "character": [
                {
                    "kind": "property",
                    "qualname": "unreal.Character.char_movement",
                    "signature": "char_movement: CharacterMovementComponent",
                    "docstring": "The CharacterMovementComponent of the character."
                }
            ]
        }
        
        results = []
        # Check fallback first to prioritize exact Unreal Engine API signatures!
        for term in query_terms:
            term_lower = term.lower()
            for key, symbols in fallback_unreal_symbols.items():
                if term_lower in key or key in term_lower:
                    results.extend(symbols)
                    
        # If we didn't find enough, search the local database
        if len(results) < len(query_terms) * 2:
            from tech_connector.models.constants import project_index_db_path
            db_path = project_index_db_path()
            if db_path.exists():
                try:
                    import sqlite3
                    with closing(sqlite3.connect(db_path)) as conn:
                        cur = conn.cursor()
                        for term in query_terms:
                            like_pattern = f"%{term}%"
                            # Filter out internal mixed-in classes to make results cleaner
                            cur.execute("""
                                SELECT symbols.kind, symbols.qualname, symbols.signature, symbols.docstring
                                FROM symbols
                                WHERE (symbols.name LIKE ? OR symbols.qualname LIKE ?)
                                  AND symbols.qualname NOT LIKE 'MainWindow%'
                                LIMIT 2
                            """, (like_pattern, like_pattern))
                            for row in cur.fetchall():
                                results.append({
                                    "kind": row[0],
                                    "qualname": row[1],
                                    "signature": row[2],
                                    "docstring": row[3]
                                })
                except Exception:
                    pass
        return results

    def run_preflight_discovery(
        self,
        prompt: str,
        emit: ProgressCallback,
        activity: ActivityCallback | None = None
    ) -> dict[str, Any]:
        """Run the same evidence-first reasoning path used by feature planning."""
        from tech_connector.services.unreal.feature_planning_service import (
            build_live_unreal_feature_plan,
        )

        emit(ProgressEvent(
            "project_discovery",
            "Inspecting the live project and preserving the prompt as a testable gameplay contract.",
            1,
            6,
        ))
        if activity:
            activity(ActivityEvent(
                "discovery",
                "Pre-flight Discovery",
                "Resolving live project ownership, dependencies, assets, and proof requirements",
                status="running",
            ))

        progress_messages: list[str] = []

        def capture(message: str) -> None:
            progress_messages.append(str(message))

        emit(ProgressEvent(
            "live_inspection",
            "Resolving the played character, current AnimBlueprint, mesh, graphs, and project defaults from Unreal.",
            2,
            6,
        ))
        plan = build_live_unreal_feature_plan(prompt, progress=capture)
        evidence = dict(plan.get("live_evidence") or plan.get("evidence") or {})

        emit(ProgressEvent(
            "semantic_index",
            "Querying the semantic project index for reusable systems and missing visibility domains.",
            3,
            6,
        ))
        visibility = dict(evidence.get("semantic_visibility") or {})
        semantic_context = dict(evidence.get("semantic_project_context") or {})

        emit(ProgressEvent(
            "technique_research",
            "Matching versioned expert techniques and retaining source claims instead of inventing an implementation recipe.",
            4,
            6,
        ))
        techniques = list(plan.get("matched_playbooks") or [])
        sources = [
            {"technique": row.get("key"), **dict(source)}
            for row in techniques
            for source in row.get("sources") or []
        ]

        emit(ProgressEvent(
            "capability_resolution",
            "Checking that every proposed operation is callable and has explicit postconditions.",
            5,
            6,
        ))
        missing_operations = sorted({
            operation
            for step in plan.get("implementation_steps") or []
            for operation in step.get("missing_operations") or []
        })
        proof_claims = list(dict(plan.get("gameplay_proof_contract") or {}).get("proof_claims") or [])
        unresolved_claims = [row.get("claim_id") for row in proof_claims if row.get("status") != "passed"]

        status = str(plan.get("status") or "evidence_failed")
        complete_message = (
            "Pre-flight has enough evidence for an approval-gated implementation plan. Runtime proof remains pending."
            if status == "approval_ready"
            else "Pre-flight found unresolved knowledge or capability evidence; mutation remains blocked or isolated."
        )
        emit(ProgressEvent("discovery_complete", complete_message, 6, 6))

        result = {
            "framework": "evidence_first_dcc_discovery_v2",
            "status": status,
            "target_asset": plan.get("target_asset"),
            "requirement_contract": plan.get("requirement_contract"),
            "architecture_decision": plan.get("architecture_decision"),
            "behavior_decomposition": plan.get("behavior_decomposition"),
            "detailed_implementation_plan": plan.get("detailed_implementation_plan"),
            "live_evidence": evidence,
            "semantic_visibility": visibility,
            "semantic_project_context": semantic_context,
            "matched_techniques": techniques,
            "technique_currency_review": plan.get("technique_currency_review"),
            "source_claims": sources,
            "missing_operations": missing_operations,
            "gameplay_proof_contract": plan.get("gameplay_proof_contract"),
            "unresolved_proof_claims": unresolved_claims,
            "planner_trace": progress_messages,
            "mutation_allowed": status == "approval_ready",
            "completion_claim_allowed": bool(proof_claims) and not unresolved_claims,
        }
        if activity:
            activity(ActivityEvent(
                "discovery",
                "Discovery Completed",
                complete_message,
                status="success" if status == "approval_ready" else "attention",
                metadata=result,
            ))
        return result
