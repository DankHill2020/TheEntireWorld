# Tech Connector Engine Asset System Plan

## Product outcome

A person arriving from Unreal, Unity, or Godot should be able to answer these
questions without documentation:

1. Where are my project assets?
2. What level am I editing?
3. What is selected and where do I change it?
4. How do I create, import, reimport, preview, instance, and find an asset?
5. Which changes are editor-only, which are synchronized to play, and which
   require a rebuild?

The target workspace is intentionally familiar:

| Familiar concept | Tech Connector home |
|---|---|
| Unreal Content Browser / Unity Project / Godot FileSystem | **Assets** |
| World Outliner / Hierarchy / Scene tree | **Scene** |
| Scene view / 3D view | **Garden** |
| Game view / PIE | **Kingdom** |
| Details / Inspector | **Inspector** |
| Import settings / Import dock | **Import** |
| Output Log / Console / Debugger | **Diagnostics** |

Garden is the authoritative asset and level authoring surface. Kingdom consumes
the same saved level and presents runtime state. A renderer limitation may keep
the runtime in a separate process, but it must not create a second asset model.

## Current audit

### Strong foundations already present

- `AssetDatabase` stores source records, dependencies, derived artifacts,
  invalidation events, and file watching.
- `.tcscene` is a versioned scene archive and already supports live changed-chunk
  publication to a connected playtest.
- `.tcimg` and `.tcskin` provide specialized image-project and skin-transfer
  persistence.
- Runtime compilation already discovers mesh, material, texture, collision,
  audio, and rig-blob dependencies.
- Static/skinned geometry, PBR and procedural materials, media textures, effects,
  physics, animation, rigging, simulation, procedural generation, and player
  packaging have meaningful implementation behind them.

### Product gaps

- `asset_type` is currently an arbitrary string, not a registered type with a
  factory, icon, importer, editor, inspector, thumbnailer, compiler, and loader.
- Stable IDs are derived from type plus source path, so a move/rename changes
  identity instead of preserving references.
- There is no project-wide Assets browser, asset creation menu, import queue,
  reimport inspector, dependency/reference viewer, redirect system, or consistent
  double-click editor routing.
- Major reusable systems are embedded in `.tcscene` metadata: runtime simulation,
  gameplay experience, character/world intelligence, procedural workspaces,
  deformation maps, and parts of material/FX authoring.
- A scene instance, source file, editable asset, and cooked runtime artifact are
  not visibly distinguished.

## Canonical model

### Four kinds of project content

1. **Source** — externally authored truth such as FBX, USD, glTF, PNG, EXR, WAV,
   OGG, VDB, Alembic, fonts, video, and source code.
2. **Authored asset** — an engine-editable resource with a persistent UUID,
   schema, properties, references, import provenance, and editor routing.
3. **Instance** — a level-local placement or component that references assets;
   it is not a duplicate asset.
4. **Derived artifact** — platform/quality-specific cooked data. It is disposable,
   reproducible, read-only, and never the authoring truth.

### Required asset descriptor

Every first-class type registers one `AssetTypeDescriptor`:

```text
type_id, display_name, family, icon, color, schema_version
extensions, creatable, importers, factory
editor_id, previewer_id, inspector_schema, thumbnailer_id
dependency_extractor, validator, cooker, runtime_loader
hot_reload_class, export_adapters, migration_chain
```

Every authored asset carries:

```text
asset_id (UUID, never path-derived)
type_id and schema_version
display_name and project-relative virtual path
source provenance and importer settings
hard, soft, editor-only, and build-only references
tags, collections, owner, revision, content hash
platform/quality overrides
```

Use a common `.tcasset` envelope for new engine-native resources and `.tcmeta`
sidecars for imported sources. Existing `.tcscene`, `.tcimg`, and `.tcskin` files
remain supported specialized containers and gain the same UUID/reference header.
Moves create temporary redirects; validation can later fix references and remove
the redirect.

## Complete asset taxonomy

Status meanings:

- **First-class** — independently persisted and broadly usable today.
- **Embedded/partial** — meaningful implementation exists but lacks the complete
  asset lifecycle.
- **Missing** — needs a new contract and/or substantial tool/runtime work.

### Project, world, and composition

| Asset types | Current | Required editor or workflow | Priority |
|---|---|---|---|
| Project manifest, project settings | First-class settings asset with guided defaults and platform overrides | Add settings search, asset picker widgets and per-section reset | P1 |
| Level / world (`.tcscene`) | First-class | Garden + Kingdom, level thumbnail, dependency summary | P0 |
| Sublevel, streaming cell, data layer | Missing | World partition/streaming panel and viewport bounds | P1 |
| Prefab / packed scene / actor archetype | Partial scene proxies | Isolated prefab mode, nested instances, override/revert/apply UI | P0 |
| Component archetype | First-class hierarchy, inheritance, replication and exposed-property asset | Add live component viewport and registered custom-component factories | P1 |
| World/environment profile | Embedded | Sky, exposure, fog, lighting and post-process preview | P1 |
| Camera, lens, camera rig | Embedded | Camera preview, pilot, bookmarks, shot handoff | P1 |
| Level sequence / cinematic | Partial animation timeline | Sequencer with tracks, cameras, audio, events and render settings | P1 |
| Level snapshot / variant set | Partial undo/snapshots | Compare, restore, variant activation and diff | P2 |

### Geometry and environment

| Asset types | Current | Required editor or workflow | Priority |
|---|---|---|---|
| Static mesh | Partial FBX/native mesh | Mesh editor: LODs, UVs, normals, materials, collision, metrics | P0 |
| Skeletal mesh | Embedded/partial | Skeletal mesh editor with skin, morphs, LOD and bounds | P0 |
| Skeleton / rig | Embedded rig graph | Skeleton hierarchy, sockets, retarget pose, validation | P0 |
| Skin binding / deformer stack | `.tcskin` + embedded | Weight/deformer editor and portable bake policy | P0 |
| Morph target / pose | Partial | Pose/morph library, sculpt/import, animation curves | P1 |
| Collision geometry | Partial cooker | Collision editor, auto-generation, complexity and debug preview | P0 |
| Terrain / landscape / height field | Partial procedural heightfield | Sculpt/paint, layers, holes, LOD, collision and streaming | P1 |
| Foliage / scatter set | Partial procedural generation | Brush/scatter rules, density, culling, variation | P1 |
| Spline / path | Partial curves | Path editor used by roads, rails, cameras and AI | P1 |
| Geometry cache / Alembic | Missing | Cache preview, frame range, interpolation and cook settings | P2 |
| Point cloud / surfel / volume mesh | Partial `.tcsurfels`/`.tcvmesh` | Specialized preview, decimation and runtime policy | P2 |
| Groom / hair | Missing | Groom groups, guides, material, LOD and simulation binding | P2 |

### Rendering, materials, and images

| Asset types | Current | Required editor or workflow | Priority |
|---|---|---|---|
| Texture 2D | Partial | Import inspector, channels, color space, mip/compression preview | P0 |
| Cube, array, 3D/volume texture | Partial GPU support | Slice/face preview and platform format settings | P1 |
| Sprite, sprite atlas, flipbook | Missing | Slice/pack editor, pivots, borders and animation preview | P1 |
| Render target | Runtime concept only | Size/format/lifetime editor and live preview | P1 |
| Material | Partial PBR contract | Material graph, live mesh preview, stats and validation | P0 |
| Material instance | Missing as asset | Parent/override UI with reset and permutation cost | P0 |
| Shader, shader graph, include/function | Partial procedural shaders | Graph/code views, compile targets, errors and generated code | P0 |
| Gradient, curve, palette | Embedded values | Reusable editors and drag/drop property references | P1 |
| Decal material | Missing | Projection preview and blend/channel controls | P1 |
| Post-process profile | Embedded rendering | Stack editor, volume blending and before/after preview | P1 |
| Environment/HDRI, sky, IES profile | Partial texture/lighting | Dedicated import and lighting previews | P1 |
| Lightmap, reflection probe, GI bake data | Partial runtime | Bake monitor, diagnostics, invalidation and size reports | P2 |
| Color-management / OCIO profile | Missing | Display/view transform and validation settings | P2 |
| Image project (`.tcimg`) | First-class | Register with Assets and texture round-trip actions | P1 |

### Animation and character

| Asset types | Current | Required editor or workflow | Priority |
|---|---|---|---|
| Animation clip / sequence | Partial takes | Timeline editor, events, curves, compression and root motion | P0 |
| Animation controller / state machine | Missing as asset | Graph, transition preview, parameters and debugger | P0 |
| Blend tree / blend space | Partial runtime concepts | 1D/2D interactive blend editor | P1 |
| Montage / animation layers | Partial | Sections, slots, sync markers and additive setup | P1 |
| Animation mask | Partial deformation maps | Skeleton tree weight editor | P1 |
| Pose library | Partial | Thumbnail grid, capture/apply/blend | P1 |
| IK rig / retarget profile | Partial rig services | Source/target mapping and live comparison | P1 |
| Control rig / procedural rig graph | Embedded | Dedicated graph + viewport + hierarchy editor | P1 |
| Physics asset / ragdoll | Partial joints/collision | Body and constraint editing with simulate mode | P1 |
| Character definition | Embedded character world | Mesh, skeleton, controller, abilities, camera and AI bundle | P1 |
| Facial rig / phoneme set | Partial blendshape support | Pose mapping, curves, audio/lipsync preview | P2 |

### FX, simulation, and physics

| Asset types | Current | Required editor or workflow | Priority |
|---|---|---|---|
| Effect system | Embedded/partial | System timeline, emitter stack, viewport and scalability | P0 |
| Effect emitter/module/function | Embedded/partial | Reusable emitter assets and module library | P1 |
| Simulation graph/profile | Embedded/partial | Solver graph, domains, fields, cache controls and profiler | P0 |
| Simulation cache | Partial runtime bake | Timeline preview, invalidation, size and platform cook | P1 |
| Physical material | Missing as asset | Friction, restitution, density and surface response | P0 |
| Force field / wind / gravity volume | Embedded | Field gizmos, falloff preview and stacking | P1 |
| Cloth | Partial solver | Paint constraints, pinning, collision, LOD and cache | P1 |
| Soft body / flesh / jiggle | Partial deformers | Material regions, collision, diagnostics and bake/export | P1 |
| Destruction / fracture collection | Partial simulation concepts | Fracture editor, clustering, damage and cache | P1 |
| Fluid / smoke / fire / goop domain | Partial multiphysics | Domain/source editor, meshing, shading and cache | P1 |
| VDB/volume cache | Missing | Volume preview, channels, transform and streaming | P2 |
| Ragdoll / constraint profile | Partial | Constraint templates and animation blending | P1 |
| Physics scene/profile | Embedded | Global gravity, timestep, solver and layer matrix | P0 |

### Audio and media

| Asset types | Current | Required editor or workflow | Priority |
|---|---|---|---|
| Audio clip / stream | Authored import settings, waveform transport, immutable-source cook | Add platform codec audition and loudness analysis | P1 |
| Sound cue / audio graph | Typed graph, concurrency, spatial and source-effect authoring | Add live voice profiler and parameter automation lanes | P1 |
| Audio mixer / bus layout | Hierarchical submix console, DSP chains, sends and snapshots | Add live meters, snapshot blending and device capture | P1 |
| Attenuation / spatial audio profile | Distance curve, spatial blend, occlusion, focus and reverb sends | Add draggable listener/source preview and plugin audition | P1 |
| Reverb / audio effect preset | Algorithmic presets and convolution reference contract | Add impulse-response browser and A/B frequency view | P2 |
| Dialogue / voice / subtitle | Missing | Speaker, localization, subtitle and lipsync references | P2 |
| Video/media source | Partial media textures | Playback, decode, color, proxy and packaging inspector | P1 |
| Media player / playlist | Missing | Timeline, looping, events and target texture | P2 |

### Gameplay, scripting, AI, and data

| Asset types | Current | Required editor or workflow | Priority |
|---|---|---|---|
| Behavior script/component | Partial Python/graph runtime | Code/graph editor, exposed properties and hot reload | P0 |
| Gameplay graph / Blueprint-like class | Embedded programs | Class/prefab editor, components, variables, events and debug | P0 |
| Data asset / custom resource | First-class schema-driven resource with inheritance, validation, cook and bundles | Add generated form controls and bulk multi-edit | P1 |
| Struct, enum, data table | First-class typed assets with inherited schemas and row validation | Add CSV round-trip UI and reference-safe field migration wizard | P1 |
| Curve/table asset | Embedded values | Curve editor and CSV import/export | P1 |
| Input action / input map | Missing | Device bindings, rebinding, contexts and live input debug | P0 |
| Game mode / ruleset / character definition | First-class ruleset and character definition with guided project assignment | Add controller/state/session asset split and live possession debugger | P1 |
| Ability, effect, attribute set | Partial gameplay concepts | Data/graph editors and network prediction flags | P2 |
| AI behavior tree / state tree | Partial intelligence services | Graph debugger, breakpoints and live agent selection | P1 |
| AI blackboard / shared memory schema | Embedded | Typed key editor and usage search | P1 |
| Navigation mesh / agent profile / query | Missing as asset | Bake preview, agents, areas, links and path debug | P1 |
| Dialogue graph / quest graph | Missing | Domain graph with localization and save-state validation | P2 |
| Save-game schema | Missing | Versioned data contract and migration testing | P2 |
| Replication profile | Partial network physics | Ownership, frequency, prediction and bandwidth inspector | P2 |

### UI, 2D, localization, and accessibility

| Asset types | Current | Required editor or workflow | Priority |
|---|---|---|---|
| UI document / widget prefab | Missing | Canvas, hierarchy, anchors, responsive preview and events | P1 |
| UI theme / style sheet | Missing | Token/theme editor with state preview | P1 |
| Font / font family | Missing | Glyph coverage, fallback, shaping and atlas settings | P1 |
| Tile set / tile map | Missing | Tile rules, terrain painting, collision and navigation | P2 |
| Localization table | Missing | Key/table editor, import/export and missing-string reports | P1 |
| Accessibility profile | Missing | Contrast, captions, input alternatives and test preview | P2 |

### Build, delivery, and diagnostics

| Asset types | Current | Required editor or workflow | Priority |
|---|---|---|---|
| Build profile / platform profile | Partial packaging | Target, configuration, scenes, signing and validation | P0 |
| Quality/scalability profile | Partial FX/runtime settings | Per-platform groups and cost preview | P1 |
| Addressable group / content bundle / DLC | Missing | Labels, dependencies, memory and remote delivery | P2 |
| Plugin/module descriptor | Partial native manifests | Dependencies, platforms and restart boundary | P2 |
| Test scene / automation specification | Partial stress scenes | Discoverable test asset and run/history UI | P2 |
| Replay / capture / benchmark | Partial physics replay | Record, inspect, compare and regression thresholds | P2 |
| Import preset | Missing | Reusable per-type/project defaults | P1 |

## Per-type definition of done

An asset type is not complete because a runtime struct exists. It is complete
only when all applicable gates pass:

1. Registered descriptor and versioned serialization.
2. Create/import/reimport path with presets and clear errors.
3. Stable UUID, dependency extraction, reference fixing, move/rename safety.
4. Thumbnail and compact hover summary.
5. Inspector schema with defaults, reset, multi-edit, undo/redo, tooltips and
   basic/advanced grouping.
6. Dedicated editor or truthful preview, including an empty state and next step.
7. Drag/drop semantics into a level or compatible property.
8. Validation, source-control state, dirty state, and save behavior.
9. Derived-data cooker plus platform and quality overrides.
10. Runtime loader, memory accounting, hot-reload class and failure fallback.
11. Export/interchange policy and loss report where applicable.
12. Unit, round-trip, corrupt-input, migration, performance and golden-preview
    coverage.

## Interaction rules familiar to engine users

- Double-click opens the correct contextual editor.
- Drag an asset into Garden to create an instance; drag it onto a compatible
  Inspector property to assign a reference.
- Right-click and `+ Add` expose the same searchable Create menu.
- Selecting a source asset shows Import; selecting an authored asset or scene
  object shows Inspector.
- `F` frames selection, `Ctrl+P` quick-opens any asset, and breadcrumbs support
  back/forward navigation.
- Rename/move is reference-safe. Delete always lists referencers and offers
  replace, fix, or cancel.
- Hover shows type, path, dimensions/duration/polycount, import status, revision,
  dependencies, and platform warnings.
- Every editor uses the same Save, Locate in Assets, Find References, Reimport,
  Validate, and Play/Preview actions.
- Basic mode shows creative controls; Advanced mode reveals compiler, solver,
  memory, platform, and low-level settings.

## Delivery phases

### Phase 0 — Asset kernel and familiar shell

Build `AssetTypeRegistry`, UUID metadata, redirect/fix-up support, source versus
derived distinction, editor routing, and a dockable Assets browser. Add searchable
Create/Import, grid/list views, breadcrumbs, filters, favorites, collections,
thumbnails, Inspector/Import routing, drag/drop, reference search, and validation.

Acceptance: a user can import, locate, rename, move, reimport, inspect, preview,
instance, find referencers, delete safely, and undo the relevant operation without
opening a command console.

### Phase 1 — Playable 3D vertical slice

First-class: Level, Prefab, Static Mesh, Skeletal Mesh, Skeleton, Skin Binding,
Animation Clip, Material, Material Instance, Shader Graph, Texture, Collision,
Physical Material, Behavior Script/Gameplay Graph, Data Asset, Input Map, Effect
System, Simulation Profile, Audio Clip, Game Ruleset, Build Profile.

Acceptance: import a character/environment, construct a reusable prefab, add
input/gameplay, play the current Garden level in Kingdom, edit a material/effect,
see live sync, and package without manually entering a path.

### Phase 2 — Specialized editors and world building

Animation state machine/blend space/retargeting, terrain, foliage, splines,
navigation, AI trees/blackboards, audio graph/mixer, cinematics, environment,
post process, render targets, sprites/atlases, UI documents, fonts, localization,
import presets.

### Phase 3 — Top-tier simulation and character assets

Cloth, soft body/flesh/jiggle, destruction, fluid/smoke/fire/goop domains,
simulation caches, VDB/geometry caches, groom/hair, physics assets, Control Rig,
facial/phoneme assets, replication profiles, replay and benchmark assets.

### Phase 4 — Large-project production

World streaming/data layers, addressable groups/DLC, multi-user locks and
ownership, source-control status, bulk operations, dependency-size analysis,
asset audit dashboards, automated migrations, redirect cleanup, headless cooks,
and qualified platform build profiles.

## First executable slice

Implement Phase 0 in this order:

1. `AssetTypeDescriptor` and `AssetTypeRegistry` with explicit built-in type IDs.
2. UUID identity and `.tcmeta` sidecars; preserve the current path-derived ID as
   a migration alias only.
3. Asset operations service for create/import/reimport/move/rename/delete/fix-up.
4. Editor/preview/inspector routing registry.
5. Assets browser integrated beside Scene in Garden and Kingdom.
6. Register the Phase 1 types already backed by runtime systems before creating
   new specialized editors.
7. Extract Material, Effect System, Simulation Profile, Gameplay Graph, Input Map,
   Data Asset, and Prefab from scene-only metadata into independently reusable
   resources while maintaining embedded-data migration.

The first demonstration should be deliberately small: import a mesh and texture,
create a material instance and prefab, place it in Garden, move the asset safely,
find its level referencer, press Play Current Level, edit one exposed value, and
observe Kingdom update without a rebuild.

## Benchmark rationale

- Unreal treats project content as assets managed through the Content Browser,
  including both imported content and engine-authored types such as Blueprints.
- Unity presents one asset workflow spanning import, authoring, build, delivery,
  and runtime loading; its Project/Hierarchy/Scene/Game/Inspector separation is
  immediately legible.
- Godot uses a broad serializable `Resource` base and treats saved scenes as
  instantiable `PackedScene` resources, while keeping import settings beside
  source files.

Tech Connector should borrow those learned interaction patterns while retaining
its differentiator: one portable scene and asset graph spanning DCC authoring,
live simulation, game runtime, and explicit interchange fallbacks.

Primary references:

- [Unreal Engine: Assets and Content Packs](https://dev.epicgames.com/documentation/en-us/unreal-engine/assets-and-content-packs-in-unreal-engine)
- [Unreal Engine: Working with Assets](https://dev.epicgames.com/documentation/unreal-engine/working-with-assets-in-unreal-engine)
- [Unreal Engine: Recommended Asset Naming Conventions](https://dev.epicgames.com/documentation/unreal-engine/recommended-asset-naming-conventions-in-unreal-engine-projects)
- [Unity 6: Asset Workflow](https://docs.unity3d.com/6000.0/Documentation/Manual/AssetWorkflow.html)
- [Unity: ScriptableObject](https://docs.unity3d.com/6000.1/Documentation/Manual/class-ScriptableObject.html)
- [Godot: Assets Pipeline](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/)
- [Godot: Resources](https://docs.godotengine.org/en/stable/tutorials/scripting/resources.html)
