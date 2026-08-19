# TC Gameplay Experience Architecture

## One Engine, Many Games

TC does not equate a game type with an engine fork. A `GameExperienceProfile` composes independent axes for simulation fidelity, systemic depth, narrative agency, player expression, competition, cooperation, learning, accessibility, and content scale. Presets provide useful requirements, but authors can combine and override them.

Presentation is a separate `PresentationProfile`. Visual Style and World Layout can be combined freely: 8-bit, 16-bit, vector, hand-painted, toon, low-poly, retro 3D, stylized real-time, photoreal, or hyper-real presentation can use 2D, layered 2.5D, full 3D, or mixed world layouts. Presentation compilation never changes gameplay or simulation contracts.

Examples include:

- A realistic educational astronomy sandbox with SI units, deterministic replay, time scrubbing, measurable learning evidence, scaffolding, and runtime creation tools.
- A narrative action RPG with responsive input, animation matching, persistent relationships, character memory, and world-scale content streaming.
- A competitive racer with vehicle dynamics, authoritative race rules, replay evidence, scalable presentation, and accessibility assists.
- A party game with fast reset, simple controls, local multiplayer, drop-in sessions, and minimal simulation cost.

## Design Contract

Each profile stores:

- Normalized experience axes instead of a single genre label.
- Simulation units, determinism, tolerance, tick rate, substeps, time scale, and authority.
- Required and optional gameplay capabilities with explicit fallbacks.
- Audience, accessibility, session, safety, and privacy requirements.
- Educational objectives with evidence, mastery thresholds, scaffolding, and standards.

Profiles are serialized as `tech_connector.game_experience.v1` in `.tcscene` metadata and are available from The Entire Scene, Python, and chat.

The code editor also provides a collapsible Engine Console. Python mode exposes the active `engine`, `world`, `game_profile`, `runtime_state`, a scene document, and `run_command` in a persistent explicit-execution namespace. TC Command mode accepts adaptive command JSON. Both modes capture output, results, errors, history, and elapsed time, and never auto-run content from files, scenes, or chat.

The Entire Scene exposes these choices through a compact Look menu. Default controls use plain names and descriptions: Visual Style, World Layout, Visual Detail, Pixel Perfect, Pixel Canvas, Animation Feel, Camera Projection, and Sprite Facing. Renderer-specific geometry, material, lighting, effect, and post-process properties remain available as advanced details instead of obscuring the primary workflow.

## Runtime Scaling

Runtime budgets derive from target platform, fidelity, and content scale. The budget separates full characters, scheduled characters, and aggregate background populations. Quality scaling must preserve gameplay state and reduce presentation cost first.

High-fidelity simulations require fixed units, deterministic replay, tolerance controls, substeps, measurable validation, and time controls. Educational games additionally require evidence events, adaptive scaffolding, teacher controls, offline operation, accessibility, consent, and child privacy where applicable.

## Gameplay Families

The initial composable presets cover realistic simulation, education, sandbox creation, action, RPG, strategy, puzzle, platformer, racing, social worlds, and party games. These presets declare capability needs; they do not claim every declared module is production-qualified.

Future profiles should add sports, rhythm, card/deckbuilding, survival, horror, immersive simulation, MMO, city building, automation, visual novel, tactics, fighting, flight, and asymmetric multiplayer without changing the scene format.

## Qualification

The profile system validates design omissions but does not replace feature qualification. Each gameplay module still needs deterministic tests, performance baselines, recovery tests, multiplayer readback, golden scenarios, stress tests, accessibility review, and multi-platform evidence before production status.
