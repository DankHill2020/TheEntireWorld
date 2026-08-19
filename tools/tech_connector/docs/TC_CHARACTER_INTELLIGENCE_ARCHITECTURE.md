# TC Character Intelligence Architecture

## Product Goal

TC characters are authored game assets, not chatbots attached to pawns. A character combines designer-owned parameters, rules, objectives, beliefs, memories, relationships, affordances, and narrative state. The same data must remain inspectable and controllable through The Entire Scene, Python, chat, and the runtime engine.

The system is useful without a downloaded model. Optional reasoning or dialogue models may propose actions or phrasing, but they cannot bypass rules or mutate world state directly.

## Authority Order

1. Engine invariants, safety rules, network authority, and designer locks.
2. World and character rules, action preconditions, and available affordances.
3. Active objectives, drives, traits, values, relationships, and remembered facts.
4. Deterministic utility scoring and stable tie breaking.
5. Optional model proposals, limited to a small scoring preference among already valid actions.

Every decision produces a why-receipt containing accepted candidates, blocked candidates, scores, rule references, and whether a model proposal was accepted. Only the selected, validated action can apply effects.

## Canonical Scene Data

`CharacterWorldAsset` is stored in `.tcscene` metadata and contains:

- Character profiles and bounded, optionally locked parameters.
- Runtime character state, blackboards, current actions, memories, and relationships.
- Explicit objectives with desired world facts, priorities, deadlines, and provenance.
- Character and world rules expressed as data conditions.
- Conditional narrative beats, effects, cooldowns, one-shot behavior, and assignments.
- Shared world facts used by gameplay, narrative, simulation, and chat tooling.

The asset uses `tech_connector.character_world.v1` so migrations can be explicit when the schema evolves.

## Scale Model

Important or nearby characters run full decisions. Mid-distance characters use scheduled updates. Distant background populations use statistical simulation. Quest-critical characters remain full fidelity regardless of distance. A future production backend should preserve the same authored contracts while batching perception, navigation, and decision work in native jobs.

## Interaction Surfaces

- Manual: The Entire Scene character and narrative tools.
- Python: `tech_connector.game_engine.runtime.tc_engine_api.engine`.
- Chat: adaptive `characters.*` and `narrative.*` commands.
- Runtime: deterministic character brain services with no UI or Qt dependency.

Scene edits participate in viewer undo, and character-world data round-trips with the scene.

## Production Roadmap

The current implementation is an interactive reference foundation, not a production-qualified NPC stack. It now includes deterministic perception receipts, navigation graphs, crowd steering, reservable smart objects, hierarchical behavior evaluation, authored dialogue acts, aggregate group simulation, and revision-checked authority. The remaining production gates are:

1. Spatial-query acceleration, dynamic navmesh generation, traversal animation, and production crowd avoidance.
2. Attention, suspicion, belief uncertainty, sensory fusion, and profiler visualization.
3. Stateful behavior execution, interruption, parallel branches, planning caches, and graph debugging.
4. Knowledge boundaries, localization, voice, interruption, performance direction, and lip sync.
5. Faction schedules, economies, ecology, crime, reputation, and rumor propagation.
6. Quest and narrative graph editing with pacing, continuity, fallback, and author overrides.
7. Multiplayer authority, replication, rollback, deterministic replay, and save migration.
8. Native batched runtime execution, budgets, profiling, stress scenes, and platform qualification.
9. Automated character evaluation for rule compliance, repetition, deadlocks, continuity, bias, and safety.

No capability should be labeled production-ready until native runtime, recovery, performance, transfer/readback, golden-scene, stress, and multi-platform evidence exist.
