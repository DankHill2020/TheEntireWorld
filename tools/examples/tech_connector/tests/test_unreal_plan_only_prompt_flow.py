import json
from pathlib import Path

from tech_connector.services.reasoning.problem_formulation_service import build_problem_formulation
from tech_connector.services.adaptive.behavior_convergence import AdaptiveBehaviorConvergence
from tech_connector.services.unreal.behavior_capability_decomposition_service import (
    _extract_narrow_repair_value,
    _critic_error_targets_field,
    _narrow_repair_needs_reasoning,
    _narrow_repair_target_has_shell,
    _repair_atomic_operations,
    _requested_global_proof_scenarios,
    _link_sibling_animation_dependencies,
    decompose_prompt_behaviors,
    requires_prompt_specific_behavior_synthesis,
    _source_precondition_phrase,
    _source_behavior_phrase,
    _source_context_guard,
    _source_context_sensing_operation,
    _is_animation_state_propagation,
    _repair_atomic_operations,
    _source_movement_mechanic,
    synthesize_novel_behavior_contract,
    validate_model_behavior_synthesis,
)
from tech_connector.services.unreal.feature_planning_service import (
    _asset_token,
    _local_operation_status,
    is_unreal_feature_plan_request,
)
from tech_connector.services.unreal.implementation_plan_synthesis_service import (
    _input_arbitration,
    _operation_realization,
    synthesize_detailed_implementation_plan,
)
from tech_connector.services.unreal import blueprint_action_discovery_service as action_discovery
from tech_connector.services.unreal import blueprint_graph_spec_service as graph_specs
from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine
from unreal_tools.blueprint import _validate_graph_spec


PROMPT = """
Repair the failed Unreal runtime observation for
/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix and
/Game/Variant_Combat/Anims/ABP_Manny_Combat. N, G, and C are unhandled;
SpaceBar only jumps; runtime traversal state and graph integration are missing.
First produce a detailed evidence-grounded implementation plan for approval.
Do not mutate Unreal assets yet.
"""


def test_foundational_blueprint_and_pie_operations_resolve_to_local_callables():
    operation_keys = [
        "blueprint.add_function",
        "blueprint.add_node",
        "blueprint.connect_node_pins",
        "blueprint.apply_graph_spec",
        "blueprint.get_compile_errors",
        "blueprint.search_node_actions",
        "blueprint.describe_node_action",
        "blueprint.probe_node_action",
        "runtime.pie_begin",
        "runtime.pie_status",
        "runtime.pie_end",
        "runtime.inject_key",
        "runtime.inspect_character",
        "runtime.validate_character_montages",
    ]

    statuses = [_local_operation_status(key) for key in operation_keys]

    assert all(status["registered"] for status in statuses)
    assert all(status["callable_found"] for status in statuses)
    assert all(status.get("source_path") for status in statuses)


def test_blueprint_action_discovery_does_not_invoke_spawners_on_raw_transient_graphs():
    root = Path(__file__).resolve().parents[3]
    cpp = (root / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "Private" / "AIStudioBridgeLibrary.cpp").read_text(encoding="utf-8")
    describe = cpp.split("FString UAIStudioBridgeLibrary::DescribeBlueprintNodeAction", 1)[1]
    describe = describe.split("FString UAIStudioBridgeLibrary::SearchBlueprintNodeActions", 1)[0]
    assert "Spawner->Invoke" not in describe
    assert "pin_probe_required" in describe


def test_blueprint_pin_probe_resets_a_retained_probe_instead_of_force_deleting_it():
    root = Path(__file__).resolve().parents[3]
    source = (root / "unreal_tools" / "blueprint.py").read_text(encoding="utf-8")
    probe = source.split("def probe_node_action(", 1)[1].split("\ndef _validate_graph_spec", 1)[0]
    assert "editor.remove_nodes([node])" in probe
    assert "probe_retained" in probe
    assert "delete_asset" not in probe


def test_semantic_action_discovery_is_read_only_and_preserves_candidate_evidence(monkeypatch):
    def fake_call(_function, kwargs, timeout=30.0):
        query = kwargs["query"]
        return {
            "ok": True,
            "returned_match_count": 1,
            "matches": [
                {
                    "palette_action": "Character|LaunchCharacter",
                    "menu_name": "Launch Character",
                    "score": 300 if query == "launch" else 100,
                }
            ],
        }

    monkeypatch.setattr(action_discovery, "_call_unreal", fake_call)
    result = action_discovery.discover_action_candidates(
        "/Game/Hero/BP_Hero",
        "EventGraph",
        [{"operation": "movement.launch_toward_observed_hit"}],
        use_reasoning=False,
    )
    assert result["ok"] is True
    assert result["mutation_allowed"] is False
    assert result["operations"][0]["selection_required"] is True
    assert result["operations"][0]["candidates"][0]["palette_action"] == "Character|LaunchCharacter"


def test_reasoning_search_terms_are_suggestions_not_success_claims(monkeypatch):
    monkeypatch.setattr(
        "tech_connector.knowledge.search.query_ollama_text",
        lambda *args, **kwargs: json.dumps(
            {
                "queries": {
                    "collision.trace_forward": [
                        "Line Trace By Channel",
                        "Capsule Trace By Channel",
                    ]
                }
            }
        ),
    )
    result = action_discovery.suggest_action_search_terms(
        [{"operation": "collision.trace_forward", "context": "forward collision query"}]
    )
    assert result["collision.trace_forward"] == [
        "Line Trace By Channel",
        "Capsule Trace By Channel",
    ]


def test_atomic_action_vocabulary_is_data_driven_and_live_evidence_scoped():
    result = action_discovery.verified_atomic_vocabulary("collision.trace_forward")
    assert "Line Trace" in result["search_terms"]
    assert "Collision|LineTraceByChannel" in result["verified_actions"]
    assert result["evidence"]["source"] == "live context-filtered FBlueprintActionDatabase reflection"


def test_known_action_discovery_uses_exact_shared_queries_without_model_expansion(monkeypatch):
    calls = []

    def fake_call(_function, kwargs, **_options):
        calls.append(kwargs["query"])
        return {"ok": True, "returned_match_count": 0, "matches": []}

    monkeypatch.setattr(action_discovery, "_call_unreal", fake_call)
    action_discovery.discover_action_candidates(
        "/Game/Hero/BP_Hero",
        "EventGraph",
        [
            {"operation": "movement.launch_forward"},
            {"operation": "movement.context_jump"},
        ],
        use_reasoning=False,
    )
    assert calls == ["Launch Character", "Jump"]


def test_live_pin_signatures_only_load_clean_reset_probes():
    signatures = graph_specs.load_verified_pin_signatures()
    assert signatures["Collision|LineTraceByChannel"]["node_title"] == "Line Trace By Channel"
    assert signatures["Animation|PlayAnimMontage"]["probe_reset"] is True


def test_graph_spec_pin_critic_accepts_real_exec_link_and_values():
    result = graph_specs.validate_graph_spec_against_pin_evidence({
        "nodes": [
            {"id": "trace", "palette_action": "Collision|LineTraceByChannel", "pin_values": {"bTraceComplex": "false"}},
            {"id": "montage", "palette_action": "Animation|PlayAnimMontage", "pin_values": {"InPlayRate": "1.0"}},
        ],
        "links": [
            {"source_node": "trace", "source_pin": "then", "target_node": "montage", "target_pin": "execute"},
        ],
    })
    assert result["ok"] is True
    assert result["mutation_allowed"] is False


def test_graph_spec_pin_critic_blocks_guessed_and_incompatible_pins():
    result = graph_specs.validate_graph_spec_against_pin_evidence({
        "nodes": [
            {"id": "trace", "palette_action": "Collision|LineTraceByChannel", "pin_values": {}},
            {"id": "jump", "palette_action": "Character|Jump", "pin_values": {"Invented": "true"}},
        ],
        "links": [
            {"source_node": "trace", "source_pin": "ReturnValue", "target_node": "jump", "target_pin": "execute"},
        ],
    })
    assert result["ok"] is False
    assert {error["code"] for error in result["errors"]} == {"unknown_value_pin", "incompatible_pin_types"}


def test_graph_spec_prompt_exposes_only_verified_actions_and_never_mutates():
    prompt = graph_specs.build_graph_spec_prompt(
        [{"operation": "collision.trace_forward"}],
        available_actions=["Collision|LineTraceByChannel", "Invented|Node"],
    )
    assert prompt["input"]["allowed_actions"] == ["Collision|LineTraceByChannel"]
    assert prompt["mutation_allowed"] is False


def test_disposable_pin_probe_requires_explicit_approval(monkeypatch):
    called = []
    monkeypatch.setattr(action_discovery, "_call_unreal", lambda *args, **kwargs: called.append(args))
    result = action_discovery.probe_selected_actions(
        "/Game/Hero/BP_Hero",
        "EventGraph",
        [{"palette_action": "Character|LaunchCharacter"}],
        approved=False,
    )
    assert result["status"] == "approval_required"
    assert result["mutation_allowed"] is False
    assert not called


def test_graph_spec_requires_explicit_nodes_values_and_valid_link_references():
    nodes, links = _validate_graph_spec({
        "nodes": [
            {"id": "input", "palette_action": "AddEvent|InputKey G", "pin_values": {}},
            {"id": "trace", "palette_action": "CallFunction|LineTraceByChannel", "pin_values": {"Trace Complex": "false"}},
        ],
        "links": [
            {"source_node": "input", "source_pin": "Pressed", "target_node": "trace", "target_pin": "execute"},
        ],
    })

    assert [node["id"] for node in nodes] == ["input", "trace"]
    assert links[0]["target_pin"] == "execute"


def test_graph_spec_rejects_unknown_link_nodes_before_unreal_mutation():
    try:
        _validate_graph_spec({
            "nodes": [{"id": "input", "palette_action": "AddEvent|InputKey G"}],
            "links": [
                {"source_node": "input", "source_pin": "Pressed", "target_node": "missing", "target_pin": "execute"},
            ],
        })
    except ValueError as exc:
        assert "unknown node id" in str(exc)
    else:
        raise AssertionError("Invalid graph spec was accepted")


def test_novel_semantic_operation_uses_graph_synthesis_without_claiming_direct_callable():
    realization = _operation_realization(
        "collision.trace_forward",
        {"operation": "collision.trace_forward", "callable_found": False},
        {
            "operation": "blueprint.apply_graph_spec",
            "callable_found": True,
            "function": "unreal_tools.blueprint.apply_graph_spec",
        },
    )

    assert realization["kind"] == "blueprint_graph_spec"
    assert realization["status"] == "pending_graph_spec"
    assert realization["execution_operation"] == "blueprint.apply_graph_spec"
    assert "exact palette action" in " ".join(realization["required_spec"])


def test_unreal_plan_only_request_preserves_targets_and_mutation_gate():
    result = build_problem_formulation(PROMPT).to_dict()

    assert result["action_mode"] == "design"
    assert result["deliverables"] == ["implementation_plan"]
    assert result["subject"]
    assert result["can_plan"] is True
    assert result["requires_clarification"] is False
    assert any("/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix" in row for row in result["knowns"])
    assert all(step["action"] not in {"modify", "execute"} for step in result["candidate_plan"])
    assert any(step["step_id"] == "decompose_behavior" for step in result["candidate_plan"])
    assert any(step["step_id"] == "define_runtime_proof" for step in result["candidate_plan"])


def test_unreal_feature_route_accepts_repair_and_uses_exact_game_asset_path():
    assert is_unreal_feature_plan_request(PROMPT)
    assert _asset_token(PROMPT) == "/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix"


def test_gameplay_invulnerability_window_does_not_route_to_desktop_windows(monkeypatch):
    plan = {
        "status": "approval_ready",
        "framework": "unreal_generic_feature_plan_v2",
        "target_asset": "/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix",
        "detected_domains": ["input", "gameplay", "validation"],
        "evidence": {},
        "implementation_steps": [],
        "validation": [],
        "rollback": [],
    }
    monkeypatch.setattr(
        "tech_connector.services.unreal.feature_planning_service.build_live_unreal_feature_plan",
        lambda *_args, **_kwargs: plan,
    )

    result = RequestEngine(progress=lambda _event: None).process(
        RequestContext(text=PROMPT, extras={"host_hint": "unreal"})
    )

    assert result.action == "clarify"
    assert result.metadata["result_type"] == "unreal_feature_plan_approval"
    assert result.metadata["engine_path"] == "unreal_live_bridge_fast_path"


def test_compact_model_behavior_is_expanded_into_recoverable_lifecycle():
    prompt = "Press G to grapple only after a forward trace hits a valid target."
    response = {
        "summary": "Trace-gated grapple movement.",
        "clause_coverage": [
            {"source_clause": "C1", "classification": "behavior", "covered_by": ["grapple_zip"]}
        ],
        "behaviors": [
            {
                "id": "grapple_zip",
                "title": "Trace-gated grapple zip",
                "source_clauses": ["C1"],
                "trigger": "G input is pressed",
                "observations": ["forward trace hit"],
                "guards": ["hit target is valid"],
                "outcomes": ["character zips toward hit point"],
                "animation_roles": [],
                "proof_scenarios": [
                    "valid hit moves toward the measured hit point",
                    "without a valid hit activation is rejected and movement remains unchanged",
                ],
                "operations": ["collision.trace_forward", "movement.launch_toward_hit"],
            }
        ],
        "proposed_atomic_operations": ["collision.trace_forward", "movement.launch_toward_hit"],
        "ambiguities": [],
        "assumptions": [],
    }

    packet = synthesize_novel_behavior_contract(
        prompt,
        model_query=lambda _system, _user: json.dumps(response),
    )

    assert packet["status"] == "validated"
    behavior = packet["synthesis"]["behaviors"][0]
    assert behavior["states"] == ["GrappleZipReady", "GrappleZipActive", "GrappleZipRecovery"]
    assert any(row["to"] == "GrappleZipRecovery" for row in behavior["transitions"])
    assert behavior["failure_paths"]


def test_behavior_critic_rejects_invented_input_key():
    prompt = "Press G to grapple after a valid trace hit."
    behavior = {
        "id": "grapple",
        "title": "Grapple",
        "source_clauses": [prompt],
        "trigger": "Player presses J",
        "observations": ["trace hit"],
        "guards": ["hit is valid"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "J input", "guards": [], "to": "Active"}],
        "outcomes": ["grapple movement"],
        "failure_paths": ["invalid hit rejects activation"],
        "proof_scenarios": ["valid hit moves character"],
        "operations": ["collision.trace_forward", "movement.grapple_zip"],
    }
    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt, "classification": "behavior", "covered_by": ["grapple"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert result["ok"] is False
    assert any("invented input keys" in error for error in result["errors"])


def test_behavior_synthesis_keeps_repairing_until_contract_is_viable():
    prompt = "Press G to grapple after a valid trace hit."
    invalid = {
        "summary": "Incomplete grapple.",
        "clause_coverage": [
            {"source_clause": "C1", "classification": "behavior", "covered_by": ["grapple"]}
        ],
        "behaviors": [],
        "proposed_atomic_operations": [],
        "ambiguities": [],
        "assumptions": [],
    }
    valid = {
        "summary": "Trace-gated grapple.",
        "clause_coverage": [
            {"source_clause": "C1", "classification": "behavior", "covered_by": ["grapple"]}
        ],
        "behaviors": [
            {
                "id": "grapple",
                "title": "Trace-gated grapple",
                "source_clauses": ["C1"],
                "trigger": "G input is pressed",
                "observations": ["forward trace hit"],
                "guards": ["trace hit is valid"],
                "outcomes": ["grapple moves toward hit"],
                "animation_roles": [],
                "proof_scenarios": [
                    "valid hit moves toward measured point",
                    "invalid hit rejects activation and preserves movement",
                ],
                "operations": ["collision.trace_forward", "movement.launch_toward_hit"],
            }
        ],
        "proposed_atomic_operations": ["collision.trace_forward", "movement.launch_toward_hit"],
        "ambiguities": [],
        "assumptions": [],
    }
    responses = iter((invalid, valid))

    packet = synthesize_novel_behavior_contract(
        prompt,
        model_query=lambda _system, _user: json.dumps(next(responses)),
    )

    assert packet["status"] == "validated"
    assert len(packet["convergence_attempts"]) == 2
    assert packet["convergence_attempts"][0]["errors"]
    assert packet["convergence_attempts"][1]["errors"] == []


def test_behavior_repair_locks_good_fields_and_omits_rejected_field():
    synthesis = {
        "clause_coverage": [
            {"source_clause": "grapple", "classification": "behavior", "covered_by": ["B1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Grapple zip",
                "source_clauses": ["grapple"],
                "trigger": "G input",
                "observations": ["trace hit"],
                "guards": ["hit-gated"],
                "outcomes": ["zip to hit"],
                "animation_roles": [],
                "proof_scenarios": ["valid hit zips"],
                "operations": ["movement.grapple_zip"],
            }
        ],
    }
    packet = AdaptiveBehaviorConvergence().repair_packet(
        {"behavior_clauses": [{"id": "C1", "text": "grapple"}]},
        synthesis,
        {"errors": ["behavior_1 guards are labels rather than executable predicates"]},
        "critic_guided_repair",
    )

    locked = packet["accepted_fields"]["behaviors"][0]
    assert "guards" not in locked
    assert locked["trigger"] == "G input"
    assert locked["operations"] == ["movement.grapple_zip"]
    assert packet["fields_to_regenerate"] == ["behaviors[0].guards"]
    assert packet["repair_candidate"] == synthesis


def test_generic_behavior_error_repairs_indexed_fields_without_losing_shell():
    synthesis = {
        "clause_coverage": [],
        "behaviors": [{"id": "B1", "trigger": "Space input is pressed"}],
    }

    packet = AdaptiveBehaviorConvergence().repair_packet(
        {}, synthesis, {"errors": ["operations are invalid"]}, "atomic_operation_rewrite"
    )

    assert packet["accepted_fields"]["behaviors"] == [
        {"id": "B1", "trigger": "Space input is pressed"}
    ]
    assert packet["fields_to_regenerate"] == ["behaviors[0].operations"]


def test_primary_error_field_does_not_flag_incidental_field_names():
    synthesis = {
        "behaviors": [{"observations": ["waist-high obstacle"], "operations": ["movement.vertical"]}],
        "clause_coverage": [],
    }
    packet = AdaptiveBehaviorConvergence().repair_packet(
        {},
        synthesis,
        {
            "errors": [
                "behavior_1 operations introduce effects not grounded by source or observations: movement.vertical"
            ]
        },
        "atomic_operation_rewrite",
    )

    assert packet["fields_to_regenerate"] == ["behaviors[0].operations"]
    assert packet["accepted_fields"]["behaviors"][0]["observations"] == ["waist-high obstacle"]


def test_narrow_repair_requires_behavior_shell_and_accepts_leaf_key_envelope():
    target = "behaviors[0].operations"

    assert _narrow_repair_target_has_shell(target, {"behaviors": [{}]})
    assert not _narrow_repair_target_has_shell(target, {})
    assert _extract_narrow_repair_value(
        {"operations": ["physics.apply_directional_impulse"]}, target
    ) == ["physics.apply_directional_impulse"]
    assert _narrow_repair_needs_reasoning("behaviors[0].guards")
    assert not _narrow_repair_needs_reasoning("behaviors[0].trigger")
    assert _source_precondition_phrase("Space context: slides while sprinting") == "sprinting"
    assert _source_behavior_phrase("Space context: slides while sprinting") == "slides"
    assert _source_behavior_phrase(
        "G input performs a hit-gated grapple zip"
    ) == "moves using requested a hit-gated grapple zip"
    assert _source_behavior_phrase(
        "Space input preserves normal jump when no traversal context exists"
    ) == "jumps using the baseline normal jump"
    assert _source_movement_mechanic("Space input context: vaults an obstacle") == "vault"
    assert _critic_error_targets_field(
        "behavior_1 surface-relative movement omits a measured surface direction or normal",
        "observations",
    )
    assert not _critic_error_targets_field(
        "behavior_1 operations are not grounded by observations", "observations"
    )


def test_reusable_operation_with_one_mechanic_term_is_semantically_specific():
    prompt = "Space context: slides while sprinting."
    synthesis = {
        "clause_coverage": [
            {"source_clause": prompt.rstrip("."), "classification": "behavior", "covered_by": ["B1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Sprint slide",
                "source_clauses": [prompt.rstrip(".")],
                "trigger": "SPACE input is pressed",
                "observations": ["character sprinting state", "current travel direction"],
                "guards": ["character sprinting state is active"],
                "outcomes": ["character moves in a slide along the current travel direction"],
                "animation_roles": [],
                "proof_scenarios": [
                    "while sprinting the character moves in a slide along the current travel direction"
                ],
                "operations": ["movement.apply_slide_impulse"],
            }
        ],
    }

    result = validate_model_behavior_synthesis(prompt, synthesis)

    assert not any("operations omit required source behavior semantics" in error for error in result["errors"])


def test_context_critic_rejects_unobserved_threshold_and_positive_only_proof():
    prompt = "Space context: slides while sprinting."
    synthesis = {
        "clause_coverage": [
            {"source_clause": prompt.rstrip("."), "classification": "behavior", "covered_by": ["B1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Sprint slide",
                "source_clauses": [prompt.rstrip(".")],
                "trigger": "SPACE input is pressed",
                "observations": ["character sprinting state"],
                "guards": ["measured velocity is greater than sprint_threshold"],
                "outcomes": ["character moves in the slide direction"],
                "animation_roles": [],
                "proof_scenarios": ["character slides in the current direction"],
                "operations": ["movement.apply_slide_impulse"],
            }
        ],
    }

    result = validate_model_behavior_synthesis(prompt, synthesis)

    assert any("unsupported symbolic tuning threshold" in error for error in result["errors"])
    assert any("observations do not provide" in error for error in result["errors"])
    assert any("negative proof for the requested precondition" in error for error in result["errors"])


def test_context_critic_rejects_unrequested_physics_effects():
    prompt = "Space context: slides while sprinting."
    synthesis = {
        "clause_coverage": [
            {"source_clause": prompt.rstrip("."), "classification": "behavior", "covered_by": ["B1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Sprint slide",
                "source_clauses": [prompt.rstrip(".")],
                "trigger": "SPACE input is pressed",
                "observations": ["character sprinting state", "current travel direction"],
                "guards": ["character sprinting state is active"],
                "outcomes": ["character slides along travel direction", "friction is set to zero"],
                "animation_roles": [],
                "proof_scenarios": [
                    "sprinting character slides along travel direction",
                    "without sprinting activation is rejected and movement remains unchanged",
                ],
                "operations": ["movement.apply_slide_impulse", "physics.set_friction_to_zero"],
            }
        ],
    }

    result = validate_model_behavior_synthesis(prompt, synthesis)

    assert any("operations introduce effects not grounded" in error for error in result["errors"])
    assert any("outcomes introduce effects not grounded" in error for error in result["errors"])


def test_behavior_critic_rejects_semantically_incomplete_grapple_contract():
    prompt = "G performs a hit-gated 2500 cm grapple zip. Do not mutate assets."
    synthesis = {
        "clause_coverage": [
            {
                "source_clause": "G performs a hit-gated 2500 cm grapple zip",
                "classification": "behavior",
                "covered_by": ["B1"],
            },
            {"source_clause": "Do not mutate assets", "classification": "constraint", "covered_by": []},
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Grapple zip",
                "source_clauses": ["G performs a hit-gated 2500 cm grapple zip"],
                "trigger": "perform",
                "observations": ["grapple zip", "distance of 2500 cm"],
                "guards": ["measured hit is valid", "distance is 2500 cm"],
                "states": ["Ready", "Active"],
                "transitions": [{"from": "Ready", "event": "perform", "guards": [], "to": "Active"}],
                "outcomes": ["hit-gated grapple zip performed"],
                "failure_paths": ["invalid hit rejects activation"],
                "animation_roles": [],
                "proof_scenarios": ["valid hit zips"],
                "operations": ["collision.trace_forward", "animation.play_grapple_zip"],
            }
        ],
    }

    result = validate_model_behavior_synthesis(prompt, synthesis)

    assert result["ok"] is False
    assert any("trigger omits requested input keys" in error for error in result["errors"])
    assert any("observations do not provide" in error for error in result["errors"])
    assert any("numeric limits" in error for error in result["errors"])
    assert any("unrequested animation" in error for error in result["errors"])
    assert any("authoritative gameplay effect" in error for error in result["errors"])
    assert any("movement, physics" in error for error in result["errors"])
    assert any("observable state or movement change" in error for error in result["errors"])
    assert any("requested actor movement effect" in error for error in result["errors"])
    assert any("numeric boundary coverage" in error for error in result["errors"])
    assert any("actor movement assertion" in error for error in result["errors"])


def test_coverage_repair_does_not_discard_valid_behavior_fields():
    synthesis = {
        "clause_coverage": [
            {"source_clause": "grapple", "classification": "behavior", "covered_by": ["C1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "trigger": "G input",
                "operations": ["movement.grapple_zip"],
            }
        ],
    }
    packet = AdaptiveBehaviorConvergence().repair_packet(
        {"behavior_clauses": [{"id": "C1", "text": "grapple"}]},
        synthesis,
        {"errors": ["coverage_1 covered_by references unknown behavior IDs: C1"]},
        "critic_guided_repair",
    )

    assert packet["fields_to_regenerate"] == ["clause_coverage"]
    assert packet["accepted_fields"]["behaviors"][0]["trigger"] == "G input"
    assert "clause_coverage" not in packet["accepted_fields"]


def test_semantic_normalization_does_not_turn_gated_into_fake_gat_concept():
    from tech_connector.services.unreal.behavior_capability_decomposition_service import _semantic_words

    assert "gate" in _semantic_words("hit-gated grapple")
    assert "gat" not in _semantic_words("hit-gated grapple")
    assert _semantic_words("character slides") & _semantic_words("character is sliding")


def test_behavior_critic_rejects_list_trigger_and_high_level_operation_placeholder():
    prompt = "G performs a hit-gated 2500 cm grapple zip."
    synthesis = {
        "clause_coverage": [
            {"source_clause": prompt.rstrip("."), "classification": "behavior", "covered_by": ["B1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Grapple zip",
                "source_clauses": [prompt.rstrip(".")],
                "trigger": ["G"],
                "observations": ["measured hit is valid", "distance is within 2500 cm"],
                "guards": ["measured hit is valid", "distance is within 2500 cm"],
                "states": ["Ready", "Active"],
                "transitions": [{"from": "Ready", "event": "G", "guards": [], "to": "Active"}],
                "outcomes": ["grapple zip performed"],
                "failure_paths": ["invalid hit rejects activation"],
                "animation_roles": [],
                "proof_scenarios": ["valid hit zips"],
                "operations": ["collision.trace_forward", "grapple.perform_zip"],
            }
        ],
    }

    result = validate_model_behavior_synthesis(prompt, synthesis)

    assert any("field trigger must be a string" in error for error in result["errors"])
    assert any("high-level placeholder actions" in error for error in result["errors"])


def test_behavior_convergence_fails_explicitly_when_repairs_make_no_progress():
    prompt = "Press G to grapple after a valid trace hit."
    invalid = {
        "summary": "Incomplete grapple.",
        "clause_coverage": [
            {"source_clause": "C1", "classification": "behavior", "covered_by": ["B1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Grapple",
                "source_clauses": ["C1"],
                "trigger": "perform",
                "observations": ["grapple"],
                "guards": ["hit-gated"],
                "outcomes": ["grapple performed"],
                "animation_roles": [],
                "proof_scenarios": ["grapple performed"],
                "operations": ["grapple.perform_action"],
            }
        ],
        "proposed_atomic_operations": ["grapple.perform_action"],
        "ambiguities": [],
        "assumptions": [],
    }

    packet = synthesize_novel_behavior_contract(
        prompt,
        model_query=lambda _system, _user: json.dumps(invalid),
    )

    assert packet["status"] == "knowledge_required"
    assert any("convergence stalled" in error.lower() for error in packet["validation"]["errors"])


def test_behavior_convergence_stops_repeated_unparseable_schema_repairs():
    calls = []

    def invalid_json(_system, _user):
        calls.append(True)
        return "{not-json"

    packet = synthesize_novel_behavior_contract(
        "Press G to grapple after a valid trace hit.",
        model_query=invalid_json,
    )

    assert packet["status"] == "knowledge_required"
    assert len(calls) == 3
    assert any("schema repair repeated" in error.lower() for error in packet["validation"]["errors"])


def test_trigger_key_matching_uses_tokens_not_letters_inside_words():
    prompt = "G performs a hit-gated grapple zip."
    behavior = {
        "id": "B1",
        "title": "Grapple",
        "source_clauses": [prompt.rstrip(".")],
        "trigger": "measured grapple hit is valid",
        "observations": ["measured grapple hit", "distance within 2500 cm"],
        "guards": ["measured grapple hit is valid", "distance is within 2500 cm"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "hit", "guards": [], "to": "Active"}],
        "outcomes": ["character moves toward hit"],
        "failure_paths": ["invalid hit rejects activation"],
        "animation_roles": [],
        "proof_scenarios": ["at boundary character moves", "above boundary activation is rejected"],
        "operations": ["collision.trace_forward", "movement.launch_toward_hit"],
    }
    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt.rstrip("."), "classification": "behavior", "covered_by": ["B1"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert any("trigger omits requested input keys: G" in error for error in result["errors"])
    assert any("input activation event" in error for error in result["errors"])


def test_numeric_boundary_error_only_regenerates_proof_scenarios():
    synthesis = {
        "clause_coverage": [],
        "behaviors": [
            {
                "id": "B1",
                "source_clauses": ["G grapple within 2500 cm"],
                "proof_scenarios": ["valid hit moves"],
            }
        ],
    }
    packet = AdaptiveBehaviorConvergence().repair_packet(
        {},
        synthesis,
        {"errors": ["behavior_1 proof_scenarios omit numeric boundary coverage"]},
        "critic_guided_repair",
    )

    assert packet["fields_to_regenerate"] == ["behaviors[0].proof_scenarios"]
    assert packet["accepted_fields"]["behaviors"][0]["source_clauses"] == ["G grapple within 2500 cm"]


def test_lifecycle_enrichment_adds_numeric_boundary_proof_without_model_help():
    response = {
        "summary": "Trace-gated grapple.",
        "clause_coverage": [
            {"source_clause": "C1", "classification": "behavior", "covered_by": ["B1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Grapple",
                "source_clauses": ["C1"],
                "trigger": "G input is pressed",
                "observations": ["trace hit is valid", "distance is within 2500 cm"],
                "guards": ["trace hit is valid", "distance is within 2500 cm"],
                "outcomes": ["character moves toward measured hit"],
                "animation_roles": [],
                "proof_scenarios": [],
                "operations": ["collision.trace_forward", "movement.launch_toward_hit"],
            }
        ],
        "proposed_atomic_operations": ["collision.trace_forward", "movement.launch_toward_hit"],
        "ambiguities": [],
        "assumptions": [],
    }
    packet = synthesize_novel_behavior_contract(
        "G performs a hit-gated 2500 cm grapple zip.",
        model_query=lambda _system, _user: json.dumps(response),
    )

    assert packet["status"] == "validated"
    proofs = packet["synthesis"]["behaviors"][0]["proof_scenarios"]
    assert any("within 2500 cm" in value for value in proofs)
    assert any("above 2500 cm" in value for value in proofs)
    assert any("character moves toward measured hit" in value for value in proofs)
    assert any("trace hit is valid" in value for value in proofs)


def test_space_and_spacebar_are_the_same_input_key():
    response = {
        "summary": "Default jump fallback.",
        "clause_coverage": [
            {"source_clause": "C1", "classification": "behavior", "covered_by": ["B1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Default jump",
                "source_clauses": ["C1"],
                "trigger": "SpaceBar input is pressed",
                "observations": ["traversal context is absent"],
                "guards": ["traversal context is absent"],
                "outcomes": ["character jumps using baseline movement"],
                "animation_roles": [],
                "proof_scenarios": [
                    "character jumps when traversal context is absent",
                    "when traversal context is present baseline jump is not activated",
                ],
                "operations": ["character.jump"],
            }
        ],
        "proposed_atomic_operations": ["character.jump"],
        "ambiguities": [],
        "assumptions": [],
    }
    packet = synthesize_novel_behavior_contract(
        "Space input preserves normal jump when no traversal context exists.",
        model_query=lambda _system, _user: json.dumps(response),
    )

    assert packet["status"] == "validated"


def test_lowercase_spacebar_trigger_is_canonicalized_without_treating_words_as_keys():
    from tech_connector.services.unreal.behavior_capability_decomposition_service import _extract_input_keys

    assert _extract_input_keys("spacebar input is pressed") == {"SPACE"}
    assert _extract_input_keys("character grapples target") == set()


def test_animation_only_clause_rejects_invented_combat_effects_and_actor_roles():
    prompt = "plays a grapple montage"
    behavior = {
        "id": "B1",
        "title": "Grapple montage",
        "source_clauses": [prompt],
        "trigger": "grapple state becomes active",
        "observations": ["grapple state is active", "montage asset is available"],
        "guards": ["grapple state is active", "montage asset is available"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "active", "guards": [], "to": "Active"}],
        "outcomes": ["grapple montage plays", "opponent is damaged"],
        "failure_paths": ["missing montage rejects playback"],
        "animation_roles": ["player", "opponent"],
        "proof_scenarios": ["grapple montage plays when available"],
        "operations": ["animation.play_montage", "physics.apply_impulse"],
    }
    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt, "classification": "behavior", "covered_by": ["B1"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert any("actors rather than animation asset roles" in error for error in result["errors"])
    assert any("invented gameplay operations" in error for error in result["errors"])
    assert any("invent non-animation gameplay effects" in error for error in result["errors"])


def test_feature_named_operation_is_rejected_in_favor_of_reusable_effect():
    prompt = "G performs a hit-gated grapple zip."
    behavior = {
        "id": "B1",
        "title": "Grapple zip",
        "source_clauses": [prompt.rstrip(".")],
        "trigger": "G input is pressed",
        "observations": ["hit point is valid"],
        "guards": ["hit point is valid"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "G", "guards": [], "to": "Active"}],
        "outcomes": ["character moves toward hit point"],
        "failure_paths": ["invalid hit rejects activation"],
        "animation_roles": [],
        "proof_scenarios": ["character moves toward hit point when hit is valid"],
        "operations": ["collision.trace_forward", "character.grapple_zip"],
    }
    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt.rstrip("."), "classification": "behavior", "covered_by": ["B1"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert any("feature-level placeholders" in error for error in result["errors"])


def test_animation_role_tokens_accept_underscored_montage_names():
    response = {
        "summary": "Play grapple montage.",
        "clause_coverage": [
            {"source_clause": "C1", "classification": "behavior", "covered_by": ["B1"]}
        ],
        "behaviors": [
            {
                "id": "B1",
                "title": "Grapple montage",
                "source_clauses": ["C1"],
                "trigger": "grapple movement is active",
                "observations": ["grapple movement is active", "montage asset is available"],
                "guards": ["grapple movement is active", "montage asset is available"],
                "outcomes": ["grapple montage plays"],
                "animation_roles": ["grapple_montage"],
                "proof_scenarios": [
                    "grapple montage plays when movement is active",
                    "without active grapple movement montage playback is rejected",
                ],
                "operations": ["animation.play_grapple_montage"],
            }
        ],
        "proposed_atomic_operations": [],
        "ambiguities": [],
        "assumptions": [],
    }
    packet = synthesize_novel_behavior_contract(
        "Play a grapple montage when grapple movement is active.",
        model_query=lambda _system, _user: json.dumps(response),
    )

    assert packet["status"] == "validated"
    assert packet["synthesis"]["proposed_atomic_operations"] == ["animation.play_grapple_montage"]


def test_generic_animation_role_is_rejected_when_mechanic_identity_is_known():
    prompt = "Play a grapple montage when grapple movement is active"
    behavior = {
        "id": "B1",
        "title": "Grapple montage",
        "source_clauses": [prompt],
        "trigger": "grapple movement is active",
        "observations": ["grapple movement is active", "montage is available"],
        "guards": ["grapple movement is active", "montage is available"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "active", "guards": [], "to": "Active"}],
        "outcomes": ["grapple montage plays"],
        "failure_paths": ["missing montage rejects playback"],
        "animation_roles": ["behavior_montage"],
        "proof_scenarios": ["grapple montage plays when movement is active"],
        "operations": ["animation.play_grapple_montage"],
    }
    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt, "classification": "behavior", "covered_by": ["B1"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert any("do not identify the source behavior" in error for error in result["errors"])


def test_unqualified_distance_rejects_inverted_minimum_guard():
    prompt = "G performs a hit-gated 2500 cm grapple zip"
    behavior = {
        "id": "B1",
        "title": "Grapple zip",
        "source_clauses": [prompt],
        "trigger": "G input is pressed",
        "observations": ["hit is valid", "distance is measured"],
        "guards": ["hit is valid", "distance is at least 2500 cm"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "G", "guards": [], "to": "Active"}],
        "outcomes": ["character moves toward measured hit"],
        "failure_paths": ["invalid hit rejects activation"],
        "animation_roles": [],
        "proof_scenarios": ["at 2500 cm character moves", "above limit activation is rejected"],
        "operations": ["collision.trace_forward", "movement.launch_toward_hit"],
    }
    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt, "classification": "behavior", "covered_by": ["B1"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert any("invert an unspecified distance limit" in error for error in result["errors"])


def test_atomic_decomposition_keeps_with_coupled_effects_together():
    from tech_connector.services.unreal.behavior_capability_decomposition_service import (
        _atomic_behavior_obligations,
    )

    rows, _lookup = _atomic_behavior_obligations(
        {
            "C1": (
                "C input performs directional dodge movement with a bounded invulnerability window "
                "and plays a dodge montage"
            )
        },
        {},
    )

    assert len(rows) == 2
    assert "with a bounded invulnerability window" in rows[0]["text"]
    assert rows[1]["text"] == "C input is pressed: plays a dodge montage"


def test_source_context_repairs_are_derived_without_inventing_hit_state():
    source = "SPACE input is pressed: vaults a waist-high obstacle"

    assert _source_context_guard(source) == "waist-high-obstacle is observed"
    assert _source_context_sensing_operation(source) == "collision.sweep_obstacle"


def test_contextual_observation_requires_a_sensing_producer():
    prompt = "SPACE input is pressed: vaults a waist-high obstacle"
    behavior = {
        "id": "B1",
        "title": "Vault",
        "source_clauses": [prompt],
        "trigger": "SPACE input is pressed",
        "observations": ["waist-high obstacle is observed"],
        "guards": ["waist-high obstacle is observed"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "SPACE input is pressed", "guards": [], "to": "Active"}],
        "outcomes": ["character vaults the waist-high obstacle"],
        "failure_paths": ["missing obstacle rejects activation"],
        "animation_roles": [],
        "proof_scenarios": ["character vaults the waist-high obstacle", "missing obstacle rejects activation"],
        "operations": ["movement.apply_vault_impulse"],
    }
    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt, "classification": "behavior", "covered_by": ["B1"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert any("contextual sensing producer" in error for error in result["errors"])


def test_bare_mechanic_operation_is_rejected_as_feature_level_placeholder():
    prompt = "SPACE input is pressed: vaults a waist-high obstacle"
    behavior = {
        "id": "B1",
        "title": "Vault",
        "source_clauses": [prompt],
        "trigger": "SPACE input is pressed",
        "observations": ["waist-high obstacle is observed"],
        "guards": ["waist-high obstacle is observed"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "SPACE input is pressed", "guards": [], "to": "Active"}],
        "outcomes": ["character vaults the waist-high obstacle"],
        "failure_paths": ["missing obstacle rejects activation"],
        "animation_roles": [],
        "proof_scenarios": ["character vaults the waist-high obstacle"],
        "operations": ["collision.sweep_obstacle", "character.vault"],
    }

    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt, "classification": "behavior", "covered_by": ["B1"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert any("feature-level placeholders" in error for error in result["errors"])


def test_atomic_operation_repair_keeps_good_members_and_fills_missing_roles():
    repaired = _repair_atomic_operations(
        "SPACE input is pressed: vaults a waist-high obstacle",
        ["collision.sweep_obstacle"],
        ["movement.apply_vertical_velocity"],
        (
            "behavior_1 operations introduce effects not grounded by source or observations: "
            "movement.apply_vertical_velocity; behavior_1 operations omit an authoritative gameplay effect"
        ),
    )

    assert repaired == ["collision.sweep_obstacle", "movement.apply_vault_impulse"]


def test_repair_packet_flags_only_the_bad_operation_member():
    synthesis = {
        "behaviors": [
            {
                "id": "B1",
                "operations": ["collision.sweep_wall", "movement.apply_jump_impulse"],
            }
        ]
    }
    validation = {
        "errors": [
            "behavior_1 operations contain redundant movement effects for one outcome: movement.apply_jump_impulse"
        ]
    }

    packet = AdaptiveBehaviorConvergence().repair_packet(
        {}, synthesis, validation, "critic_guided_repair"
    )
    diagnostic = packet["field_diagnostics"]["behaviors[0].operations"]

    assert diagnostic["status"] == "partially_rejected"
    assert diagnostic["accepted_items"] == ["collision.sweep_wall"]
    assert diagnostic["rejected_items"] == ["movement.apply_jump_impulse"]


def test_critic_rejects_guard_in_trigger_and_unrelated_dodge_trace():
    prompt = "C input performs directional dodge movement with a bounded invulnerability window while grounded"
    behavior = {
        "id": "B1",
        "title": "Dodge",
        "source_clauses": [prompt],
        "trigger": "C input is pressed while grounded",
        "observations": ["character is grounded", "observed input movement direction"],
        "guards": ["character is grounded", "invulnerability window is within bounds"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "C input is pressed", "guards": [], "to": "Active"}],
        "outcomes": ["character dodges along the observed input direction", "invulnerability is bounded"],
        "failure_paths": ["not grounded rejects activation"],
        "animation_roles": [],
        "proof_scenarios": ["character dodges along the observed input direction", "not grounded rejects activation"],
        "operations": [
            "collision.trace_forward",
            "physics.apply_directional_dodge_impulse",
            "combat.enable_bounded_invulnerability_window",
            "combat.schedule_invulnerability_clear",
        ],
    }
    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt, "classification": "behavior", "covered_by": ["B1"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert any("trigger embeds a source precondition" in error for error in result["errors"])
    assert any("circular invulnerability precondition" in error for error in result["errors"])
    assert any("sensing not grounded" in error for error in result["errors"])


def test_requested_pie_categories_are_explicit_global_obligations():
    prompt = "Require positive, negative, boundary, interruption, and regression PIE proof."
    proofs = _requested_global_proof_scenarios(prompt)

    assert len(proofs) == 5
    missing = validate_model_behavior_synthesis(prompt, {"behaviors": [], "clause_coverage": []})
    assert sum("global proof_scenarios omit requested" in error for error in missing["errors"]) == 5


def test_animation_sibling_waits_for_gameplay_activation_success():
    linked = _link_sibling_animation_dependencies(
        [
            {
                "id": "move",
                "title": "Grapple Zip",
                "_parent_clause_id": "C1",
                "source_clauses": ["G input performs a grapple zip"],
                "trigger": "G input is pressed",
                "observations": ["hit is valid"],
                "guards": ["hit is valid"],
                "outcomes": ["character moves toward hit"],
                "animation_roles": [],
                "proof_scenarios": ["character moves toward hit"],
                "operations": ["movement.launch_toward_observed_hit"],
            },
            {
                "id": "presentation",
                "title": "Grapple Montage",
                "_parent_clause_id": "C1",
                "source_clauses": ["G input is pressed: plays a grapple montage"],
                "trigger": "G input is pressed",
                "observations": ["G input received"],
                "guards": ["G input received"],
                "outcomes": ["grapple montage plays"],
                "animation_roles": ["grapple_montage"],
                "proof_scenarios": ["grapple montage plays"],
                "operations": ["animation.play_grapple_montage"],
            },
        ]
    )

    assert linked[1]["depends_on"] == ["move"]
    assert linked[1]["trigger"] == "grapple_zip activation succeeds"
    assert linked[1]["transitions"][0]["event"] == "grapple_zip activation succeeds"


def test_contextual_input_arbitration_orders_state_world_locomotion_then_fallback():
    rows = _input_arbitration(
        [
            {"id": "fallback", "title": "Jump", "trigger": "SPACE input is pressed", "guards": ["traversal context does not exist"]},
            {"id": "slide", "title": "Slide", "trigger": "SPACE input is pressed", "guards": ["character is sprinting"]},
            {"id": "vault", "title": "Vault", "trigger": "SPACE input is pressed", "guards": ["waist-high obstacle is observed"]},
            {"id": "wall", "title": "Wall Jump", "trigger": "SPACE input is pressed", "guards": ["character is climbing"]},
            {"id": "montage", "title": "Wall Montage", "trigger": "wall activation succeeds", "guards": ["wall activation succeeds"], "depends_on": ["wall"]},
        ]
    )

    assert [value["behavior_id"] for value in rows[0]["ordered_candidates"]] == [
        "wall", "vault", "slide", "fallback"
    ]
    assert rows[0]["fallback_behavior_id"] == "fallback"
    assert rows[0]["unresolved_ties"] == []


def test_space_arbitration_uses_outcome_context_when_model_guards_are_sparse():
    rows = _input_arbitration(
        [
            {"id": "vault", "title": "Vault Waist-High Obstacles", "trigger": "SPACE input is pressed", "guards": ["activation is available"], "outcomes": ["character vaults waist-high obstacles"]},
            {"id": "slide", "title": "Slide", "trigger": "SPACE input is pressed", "guards": ["character is sprinting"], "outcomes": ["character slides"]},
            {"id": "jump", "title": "Preserve Jump", "trigger": "SPACE input is pressed", "guards": ["activation is available"], "outcomes": ["character jumps using the baseline jump"]},
        ]
    )
    assert [value["behavior_id"] for value in rows[0]["ordered_candidates"]] == ["vault", "slide", "jump"]
    assert rows[0]["fallback_behavior_id"] == "jump"
    assert rows[0]["unresolved_ties"] == []


def test_detailed_plan_blocks_approval_until_animation_and_callable_evidence_exist():
    behavior = {
        "selected_primitives": [
            {
                "id": "dodge",
                "key": "generated.dodge",
                "title": "Dodge",
                "source_clauses": ["C input performs a dodge"],
                "trigger": "C input is pressed",
                "observations": ["input direction"],
                "guards": ["dodge activation is available"],
                "outcomes": ["character dodges along input direction"],
                "operations": ["physics.apply_directional_dodge_impulse"],
                "animation_roles": ["dodge_montage"],
            }
        ],
        "proof_scenarios": [],
    }
    plan = synthesize_detailed_implementation_plan(
        "C input performs a dodge and plays a dodge montage",
        requirement_contract={"explicit": {}},
        project_context={
            "target_asset": "/Game/BP_Character",
            "animation_blueprint": "/Game/ABP_Character",
            "target_skeleton": "/Game/SK_Character",
        },
        architecture_decision={},
        techniques=[],
        implementation_steps=[],
        operation_status=[],
        gameplay_proof_contract={},
        animation_candidates=[],
        behavior_decomposition=behavior,
    )

    assert plan["readiness"]["ready_for_approval"] is False
    assert plan["readiness"]["unresolved_behavior_operations"] == [
        "dodge:physics.apply_directional_dodge_impulse"
    ]
    assert any("Animation role assets" in value for value in plan["readiness"]["errors"])
    assert len(plan["proof_plan"]["fixtures"]) == 3


def test_broad_static_keyword_matches_do_not_hide_compound_input_obligations():
    prompt = (
        "G input performs a grapple zip and plays a grapple montage. "
        "Space input vaults an obstacle, slides while sprinting, and wall-jumps while climbing. "
        "C input performs a directional dodge and plays a dodge montage."
    )
    static = decompose_prompt_behaviors(prompt)

    assert static["knowledge_required"] is False
    assert requires_prompt_specific_behavior_synthesis(prompt, static) is True


def test_validated_obligations_survive_when_a_later_obligation_needs_knowledge():
    prompt = "G input grapples. State reaches the AnimBlueprint every update."
    partial = {
        "status": "knowledge_required",
        "synthesis": {
            "behaviors": [
                {
                    "id": "O1_C1",
                    "title": "Grapple",
                    "source_clauses": ["G input grapples"],
                    "trigger": "G input is pressed",
                    "observations": ["observed grapple target"],
                    "guards": ["observed grapple target is valid"],
                    "outcomes": ["character moves toward the grapple target"],
                    "operations": ["movement.launch_toward_observed_hit"],
                    "animation_roles": [],
                    "proof_scenarios": ["character moves toward the grapple target"],
                }
            ]
        },
        "validation": {"ok": False, "errors": ["later obligation needs knowledge"]},
        "failed_obligation": {
            "id": "C2",
            "text": "State reaches the AnimBlueprint every update",
        },
    }

    result = decompose_prompt_behaviors(prompt, model_synthesis=partial)

    assert [row["title"] for row in result["selected_primitives"] if not row.get("always")] == ["Grapple"]
    assert result["selected_primitives"][0]["source"] == "validated_partial_model_synthesis"
    assert result["unmatched_behavior_clauses"] == ["State reaches the AnimBlueprint every update"]
    assert result["knowledge_required"] is True


def test_all_failed_obligations_remain_visible_beside_validated_partial_work():
    prompt = "G input grapples. C input dodges. State reaches the AnimBlueprint every update."
    partial = {
        "status": "knowledge_required",
        "synthesis": {
            "behaviors": [
                {
                    "id": "O1_C1",
                    "title": "Grapple",
                    "source_clauses": ["G input grapples"],
                    "trigger": "G input is pressed",
                    "observations": ["observed grapple target"],
                    "guards": ["observed grapple target is valid"],
                    "outcomes": ["character moves toward the grapple target"],
                    "operations": ["movement.launch_toward_observed_hit"],
                    "animation_roles": [],
                    "proof_scenarios": ["character moves toward the grapple target"],
                }
            ]
        },
        "validation": {"ok": False, "uncovered_clauses": []},
        "failed_obligation": {"id": "C2", "text": "C input dodges"},
        "failed_obligations": [
            {"id": "C2", "text": "C input dodges"},
            {"id": "C3", "text": "State reaches the AnimBlueprint every update"},
        ],
    }

    result = decompose_prompt_behaviors(prompt, model_synthesis=partial)

    assert result["unmatched_behavior_clauses"] == [
        "C input dodges",
        "State reaches the AnimBlueprint every update",
    ]
    assert [row["title"] for row in result["selected_primitives"] if not row.get("always")] == ["Grapple"]


def test_later_space_key_does_not_leak_into_earlier_climb_obligations():
    from tech_connector.services.unreal.behavior_capability_decomposition_service import _atomic_behavior_obligations

    rows, _lookup = _atomic_behavior_obligations(
        {"C1": "supports climb, hang, clean exit, and Space wall-jump to another wall"},
        {},
    )
    assert [row["text"] for row in rows] == [
        "supports climb",
        "hang",
        "clean exit",
        "SPACE input is pressed: wall-jump to another wall",
    ]

    contextual_rows, _lookup = _atomic_behavior_obligations(
        {"C1": "Climbing begins at a wall, supports climb, hang, clean exit, and Space wall-jump"},
        {},
    )
    assert [row["text"] for row in contextual_rows] == [
        "Climbing begins at a wall",
        "Climbing: supports climb",
        "Climbing: hang",
        "Climbing: clean exit",
        "SPACE input is pressed: wall-jump",
    ]


def test_global_contextual_montage_request_attaches_roles_to_each_behavior():
    from tech_connector.services.unreal.behavior_capability_decomposition_service import _apply_global_animation_presentation

    rows = _apply_global_animation_presentation(
        "Contextually correct montages must play.",
        [{"id": "dodge", "title": "Directional Dodge", "operations": ["physics.apply_directional_impulse"]}],
    )
    assert rows[0]["animation_roles"] == ["directional_dodge_montage"]
    assert rows[0]["operations"][-1] == "animation.play_contextual_montage"


def test_anim_blueprint_state_propagation_lowers_to_reusable_read_and_write_effects():
    source = "State reaches ABP_Manny_Combat every update"

    assert _is_animation_state_propagation(source)
    assert _source_context_guard(source) == "ABP_Manny_Combat AnimInstance is valid"
    assert _repair_atomic_operations(
        source,
        [],
        [],
        "behavior_1 missing operations; operations omit required source behavior semantics",
    ) == [
        "state.read_owning_character_variables",
        "state.write_anim_instance_variables",
    ]


def test_animation_input_guard_is_derived_from_requested_key():
    assert _source_context_guard(
        "G input is pressed: plays a grapple montage"
    ) == "G input activation is received"
    assert _repair_atomic_operations(
        "G input is pressed: plays a grapple montage",
        ["animation.play.grapple_montage"],
        [],
        "operations are feature-level placeholders; animation-only request omits an animation operation",
    ) == ["animation.play_grapple_montage"]


def test_surface_relative_movement_rejects_invented_tuning_and_missing_normal():
    prompt = "Space context: wall-jumps while climbing"
    behavior = {
        "id": "B1",
        "title": "Wall jump",
        "source_clauses": [prompt],
        "trigger": "Space input is pressed",
        "observations": ["wall is within 2 meters", "character is climbing"],
        "guards": ["wall is within 2 meters", "character is climbing"],
        "states": ["Ready", "Active"],
        "transitions": [{"from": "Ready", "event": "Space", "guards": [], "to": "Active"}],
        "outcomes": ["character jumps forward"],
        "failure_paths": ["missing wall rejects activation"],
        "animation_roles": [],
        "proof_scenarios": ["character jumps when wall is within 2 meters"],
        "operations": ["movement.jump_forward", "physics.apply_gravity"],
    }
    result = validate_model_behavior_synthesis(
        prompt,
        {
            "clause_coverage": [
                {"source_clause": prompt, "classification": "behavior", "covered_by": ["B1"]}
            ],
            "behaviors": [behavior],
        },
    )

    assert any("invented numeric constants" in error for error in result["errors"])
    assert any("surface direction or normal" in error for error in result["errors"])
    assert any("directional basis" in error for error in result["errors"])
    assert any("outcome omits the measured surface basis" in error for error in result["errors"])
