# TC Engine Authoring Experience

## One Capability, Three Entrances

Engine features must expose the same intent and receipt through:

- Manual authoring in The Entire Scene.
- The stable `tc_engine_api.engine` Python API.
- Chat through registered adaptive `engine.*` commands.

Manual controls, code, and chat do not own separate implementations. They submit
the same target, creative goal, constraints, and overrides to the same service.

Graph View and Code View also edit one canonical `EngineGraphProgram`. Stable node
identities preserve graph layout while supported Python edits update node operations,
literal properties, and data connections directly. Each scene entry stores the
graph, synchronized source, and native-runtime manifest together. See
`TC_NATIVE_ENGINE_AND_GRAPH_ARCHITECTURE.md` for the language split, reversible
authoring rules, friendly property contract, and native compilation ladder.

## Package Boundary

- `tech_connector.engine` remains the intelligence and reasoning engine.
- `tech_connector.game_engine` is the public game-runtime and authoring package.
- `tech_connector.game_engine.scene` owns native scene documents, coordinate
  conversion, scene deltas, import conversion, and compilation.
- `tech_connector.game_engine.authoring` owns modeling, animation takes, rig
  graphs, rig templates, and authoring workspaces.
- `tech_connector.game_engine.deformation` owns paintable maps, simulation-mesh
  bindings, skinning contracts, GPU skinning, jiggle, and native deformers.
- `tech_connector.game_engine.runtime` owns effects, simulation, collision,
  scalability, runtime APIs, playtest iteration, and live scene updates.
- `tech_connector.game_engine.integration` owns DCC bridges, viewport streams,
  command routing, snapshots, transfer policy, and host-thread adaptation.
- `tech_connector.services.dcc` is compatibility-only. Its modules are true
  aliases to canonical `game_engine` modules so existing scripts share the same
  registries, caches, monkeypatches, and singleton state.

New game systems should enter through `game_engine`; Viewer modules should only
adapt those systems to Qt interaction and visualization. Core scene, authoring,
deformation, and runtime modules must not depend on Qt or host DCC APIs; those
dependencies belong in `integration` or `tech_connector.ui`.

The procedural content architecture and parity ladder are maintained in
`TC_PROCEDURAL_ENGINE.md`.

## Deformation Maps

Every skin cluster and ordered deformer can own an independent output map. Zero
preserves the upstream mesh, one follows the deformed result, and fractional
values blend continuously. Jiggle is an ordered secondary-motion deformer with
its own map and can follow skin clusters, arbitrary deformers, simulation meshes,
or effect emitters. Maps are sparse in scene receipts and remain editable through
the Viewer brush, Python API, and adaptive chat commands.

Fleshy skin is authored as a collision-responsive ordered deformer after the
canonical skin cluster. It never replaces or renormalizes joint weights. TC scene
and `.tcskin` payloads preserve the flesh settings as an optional extension while
FBX, USD, glTF, Maya, Blender, Houdini, Unreal, and Unity continue to receive the
authoritative skeleton and skin weights. Destinations without a compatible flesh
solver use an explicit morph/blend-shape or point-cache bake fallback.

Jiggle uses the same collision inputs as flesh and adds driver-velocity follow,
per-axis freedom, travel and speed limits, friction, bounce, settling, quality,
and per-deformer timing/contact telemetry. Large independent vertex sets use a
vectorized CPU path. The Skinning menu exposes shared-map preset stacks for
subtle skin, soft tissue, belly/chest, facial tissue, cartilage, ears/tendrils,
tail overlap, muscle follow-through, and stylized goop. Presets are starting
points: every underlying jiggle and flesh property stays editable. Their TC
extension and destination bake policy remain optional, so canonical joint
weights can always move independently to Maya, Blender, Houdini, Unreal, Unity,
USD, FBX, or glTF.

## Guided By Default

The default runtime setup asks where the experience will run and what matters
most. It reports each feature as Ready, Compatible Alternative, or Needs
Attention. Advanced mode exposes quality profiles, tick rate, backend selection,
solver controls, and detailed receipts without making those concepts mandatory.

## Capability Maturity

Routing support and production readiness are reported separately. A command may
be routable without being production-qualified. TC uses sequential evidence gates:

- `contract`: stable intent, schema, and route are registered.
- `reference`: a local executor has deterministic headless tests.
- `interactive`: the same executor is reachable through a user-facing UI, API,
  graph, or chat entry point.
- `production`: a native backend has measured performance, recovery coverage,
  and destination import/readback validation.
- `qualified`: golden scenes, stress suites, and at least two supported platform
  qualifications pass.

Missing gates remain visible in command catalogs and audit receipts. The legacy
`implemented` flag continues to mean that routing is enabled; it no longer
implies production readiness.

## Save-To-Game Loop

Saving a `.tcscene` computes stable hashes for dependency-aware scene chunks.
Only changed chunks are sent to connected game/playtest sessions:

- `hot_swap`: apply while preserving the running game state.
- `state_migration`: replace compatible systems and migrate supported state.
- `restart_required`: native runtime, platform, or plug-in changes need restart.

An unchanged save sends no packet. Packaging is not part of normal local
iteration; it remains necessary for distribution, signing, platform deployment,
or executable/runtime changes.

## Playtest Loop

The preferred playtest workflow launches a reusable session once and keeps it
connected. Scene, effects, materials, parameters, and compatible gameplay changes
then update incrementally. Remote-device packaging rebuilds only changed runtime
chunks plus their dependency closure when a restart is genuinely required.

Every update returns a plain-language summary and a technical receipt containing
scene revision, changed chunk IDs, compatibility class, deliveries, and failures.
