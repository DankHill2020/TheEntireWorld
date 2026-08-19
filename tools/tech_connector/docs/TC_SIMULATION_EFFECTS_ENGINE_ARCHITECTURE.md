# TC Simulation, Cloth, and Effects Engine Architecture

## Product Contract

TC authors one nondestructive simulation asset and compiles it for cinematic,
photoreal realtime, mobile, toony, stylized, or retro playback. The source graph
is never replaced by a bake. Every approximation is visible in a compile receipt.

The engine must provide:

- Direct TC runtime playback without requiring another DCC or game engine.
- Deterministic reference evaluation for tests, review, and cache validation.
- Native CPU and GPU backends behind the same simulation IR.
- Explicit target budgets and graceful, inspectable degradation.
- Live manipulation, background baking, and resumable caches.
- Engine transfer through native graphs when possible and validated caches when not.

## Layered Architecture

1. Authoring graph
   - Solver-independent nodes, materials, masks, events, fields, colliders, and render intent.
   - Stable IDs and undoable transactions.
   - Variants inherit from a source graph and store overrides only.

2. Canonical simulation IR
   - Typed resources, ordered stages, dependencies, precision, domains, and output contracts.
   - No UI classes or backend-specific handles.
   - Validates resource access, unsupported domains, topology-change policy, and determinism.

3. Backend compiler
   - Reference CPU: correctness, deterministic tests, headless fallback.
   - Native CPU: SIMD, task graph, CPU/GPU overlap, server and low-end fallback.
   - GPU compute: structure-of-arrays buffers, graph-colored constraints, GPU broadphase,
     sparse tiled grids, indirect dispatch, and asynchronous readback.

4. Render graph
   - Sprites, meshes, ribbons, beams, trails, decals, lights, strands, surfaces, and volumes.
   - Shared material intent with photoreal, toony, stylized, and retro render implementations.
   - Motion vectors, temporal stability, transparency, refraction, deep shadows, and path-traced validation.

5. Runtime and cache layer
   - Fixed-step runtime, interpolation, rollback snapshots, replication events, and simulation LOD.
   - Content-addressed frame chunks with topology-change receipts.
   - Alembic, USD, OpenVDB, VAT, flipbook, point-cache, and target-plugin outputs.

## UX Architecture

### Progressive Disclosure

- Create: task-oriented presets such as Garment, Smoke, Liquid, Destruction, Weather, and Magic.
- Direct: grab, pin, fold, stitch, cut, paint, and move colliders in the viewport.
- Tune: a concise Summary panel exposes the controls that materially affect the current result.
- Inspect: advanced graph, attributes, constraints, stage timings, and memory are available without changing modes.
- Compile: quality/platform variants appear as tabs with differences and fallbacks summarized.

The default interface must never show every solver parameter at once.

### Viewport Interaction

- Selection and manipulators remain available while simulation is running.
- Painting supports material, pin, collision, tear, wetness, burn, emission, and solver-detail masks.
- A Vellum-style brush can push, smooth, inflate, fold, freeze, relax, and restore simulation state.
- Space-time guides direct motion over a frame range without keying every particle.
- An intent solver can search bounded parameter ranges for requests such as tighter folds or less bounce.

### State Model

Every simulation surface displays exactly one state:

- Live: current graph and parameters are executing.
- Dirty: authored data changed after the last cache.
- Compiling: IR or shaders are rebuilding in the background.
- Baking: deterministic cache generation is active and cancelable.
- Cached: validated frames exist for the current graph hash.
- Fallback: requested backend or feature was replaced; the reason is visible.
- Error: execution stopped with a focused repair action.

Opening a property must not trigger a bake. Parameter changes update live previews at
interactive quality and mark production caches dirty.

### Diagnostics

- Cloth: stretch, compression, bend, strain, thickness, contact, friction, tear, and convergence overlays.
- Effects: particle count, overdraw, bounds, occupancy, event rate, grid slices, temperature, velocity, and divergence.
- Runtime: stage timings, dispatch count, CPU/GPU synchronization, allocation, bandwidth, and cache throughput.
- Recommendations explain the cost and expected visual effect before applying a fix.
- A/B compare and parameter wedges share camera, time, lighting, and seed.

## Scalability Contract

Each compiled profile declares:

- Target simulation milliseconds and render milliseconds.
- Particle, constraint, collider, event, light, trail, and volume-cell budgets.
- Solver precision, substeps, iterations, and topology-change policy.
- Update frequency, visibility and distance culling, and importance weighting.
- Required visual invariants such as silhouette, timing, contacts, and material identity.

The compiler may change representation but cannot silently violate an invariant.

### Degradation Order

1. Cull invisible render work while preserving simulation needed by gameplay.
2. Reduce secondary particles, trails, lights, and detail emitters.
3. Reduce update frequency with interpolation.
4. Reduce volume resolution or switch 3D domains to 2D/local domains.
5. Swap stateful effects for a validated stateless implementation.
6. Swap live simulation for a cache, VAT, flipbook, skeletal proxy, or impostor.
7. Disable only optional features explicitly marked disposable by the author.

### Scheduling

- Batch systems sharing code and resources.
- Pool components and buffers; avoid runtime allocation.
- Execute independent islands concurrently.
- Use async compute when it does not extend the critical frame path.
- Stream cache and sparse-grid pages by camera and importance.
- Keep GPU state resident and read back only requested diagnostics or gameplay events.

## Cloth Requirements

- Warp, weft, bias, anisotropic bend, damping, strain limits, thickness, and measured density.
- Continuous vertex-face and edge-edge self-collision with multilayer contact caching.
- Animated SDF and mesh colliders, collision groups, exclusions, and painted friction.
- Separate simulation/render meshes with stable transfer and dynamic wrinkle synthesis.
- Stitch, slide, weld, cut, tear, fray, pressure, plasticity, wetness, burn, and freeze.
- Deterministic topology events suitable for runtime replication and cache deltas.

## Effects Requirements

- Typed system, emitter, particle, grid, event, and render stages.
- Reusable modules, custom attributes, curves, parameter collections, and data interfaces.
- Stateful and stateless compilation paths.
- Particle, PBD, SPH, FLIP/APIC/MPM, rigid, grain, and sparse-volume stages.
- Cross-domain coupling through explicit exchange stages rather than hidden side effects.
- Renderers for particles, surfaces, strands, volumes, decals, lights, and distortion.

## Production Gates

A capability is not production-ready until it has:

- Golden scenes with numerical and image baselines.
- Determinism checks across repeated runs and supported devices.
- Stress tests for fast colliders, stacked cloth, topology changes, and large coordinates.
- Measured frame, memory, upload, and cache budgets.
- Undo, cancel, crash recovery, and dirty-cache tests.
- Import/export readback validation for every claimed target.
- A clear fallback for unsupported hardware and target engines.

## Delivery Sequence

1. Canonical IR, profiles, reference execution, receipts, and profiler schema.
2. Native CPU particle/constraint backend and collision acceleration structures.
3. GPU particles, graph-colored XPBD cloth, GPU broadphase, and live diagnostics.
4. Production cloth materials, CCD, multilayer contacts, topology tearing, and multires wrinkles.
5. Effects graph, stateless compiler, GPU events, and renderer streams.
6. Sparse volume solver and physically based/stylized volume rendering.
7. Multiphysics exchange stages, background bake farm, and target-engine compilers.

## Current Runtime Status

Implemented and covered by headless tests:

- Backend-neutral compiled simulation IR and execution profiles.
- Deterministic reference CPU execution without Qt or an external DCC.
- Fixed 60 Hz-style ticking with bounded catch-up and interpolation packets.
- Runtime event streams, renderer-grouped particle streams, and live parameters applied on tick boundaries.
- Runtime quality/profile switching, checkpoints, rollback, and deterministic command replay.
- Deployment and transfer manifests that explicitly declare no editor requirement.
- Runtime compilation and execution smoke coverage for every built-in effect preset.
- Replaceable backend executors so native CPU and GPU runtimes use the same authored asset.

Still required before a production game-runtime claim:

- Native SIMD/task-graph CPU executor and compute GPU executor.
- GPU-resident particle, constraint, collision, event, and indirect-render buffers.
- Production cloth self-contact/CCD, tearing, remeshing, multilayer friction, and wrinkle validation.
- Production sparse-fluid/combustion solver and physically based volume renderer.
- Engine renderer integration for mesh particles, ribbons, beams, decals, lights, distortion, refraction, and volumes.
- Replication codecs, platform determinism qualification, memory pools, streaming simulation LOD, and stress baselines.
