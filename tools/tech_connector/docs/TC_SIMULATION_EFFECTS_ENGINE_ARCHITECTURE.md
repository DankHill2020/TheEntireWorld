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
- Typed bounded FX Data Channels with schema validation, retention, overflow policies,
  event bindings, deterministic tick publishing, and shared listener systems.
- Versioned reusable FX subgraph contracts with typed sockets, dependency validation,
  cycle detection, and compiled-IR declarations.
- Truthful per-tick execution receipts that distinguish compiled, selected, and actual
  backends while reporting residency, timing, budget status, memory, and channel pressure.
- Viewer/chat commands to create channels, publish gameplay payloads, inspect execution
  plans, and inspect live FX profiler history.
- Installed native CPU particle/effect executor with reusable NumPy structure-of-arrays
  allocations, vectorized supported fields and primitive collisions, explicit stage/upload/
  download telemetry, and capability-gated reference fallback.
- Opt-in buffer-authoritative output lets native renderer/compute consumers reuse particle
  state across ticks with zero compatibility synchronization, plus explicit zero-copy view
  and object-model readback APIs. The synchronized path remains the default.
- Compute-provider boundary with persistent host/device buffer contracts and truthful NumPy
  CPU/CuPy CUDA discovery. CUDA remains unavailable unless a working provider and solver
  kernels are both present; provider discovery alone never claims GPU execution.
- Native/reference equivalence, persistent-allocation, fallback, and 20k-particle stress tests.
- Deterministic graph-colored native XPBD distance and area constraints, attachment solving,
  ragged closed-volume preservation, plastic/breakable distance state, and stable spatial-hash
  viscosity/cohesion neighbors for liquid, goo, and jello-style materials.
- A working provider-neutral GPU particle executor with persistent float32 device buffers,
  supported force fields, plane/sphere collisions, resident reuse, and asynchronous-ready
  transfer boundaries. Qualified native D3D11 is selected on Windows, with CuPy/CUDA as the
  portable array-provider path; `gpu_compute` is installed only after a real device probe.
- Native deterministic spatial-hash self-contact, BVH/refittable triangle-mesh collision,
  moving-surface response, and reformable bond creation/healing/breaking now execute inside
  the resident particle pipeline instead of forcing reference playback.
- Persistent native sparse-volume SoA state covers vectorized dissipation, fuel/flame,
  cooling, buoyancy, compaction, memory, and active-cell telemetry with reference baselines.
- Native and provider-GPU volume buffers support explicit authoritative residency, zero-transfer
  repeat ticks, deferred compaction/readback, and safe ownership handoff to CPU execution.
- The provider-neutral GPU path includes graph-colored float32 XPBD distance/area constraints,
  attachments, bounded pairwise self/material neighbors, and persistent sparse combustion
  buffers. It also includes a bounded vector particle/triangle closest-point kernel with moving
  mesh response. Pairwise work fails closed above 2,048 particles and mesh work above two
  million particle-triangle candidates.
- The native D3D11 path now keeps distance-constraint endpoint, parameter, lambda, position,
  and velocity buffers resident per independent world session. Deterministic graph coloring
  removes write conflicts, XPBD compliance is solved on-device, compiled profile iterations
  are honored, and upload/readback/dispatch telemetry includes the constraint stage. Collapsed
  links recover from relative velocity with a deterministic axis fallback. Breaking, plasticity,
  and reforming remain explicitly capability-gated to native CPU rather than silently diverging.
- Authoritative D3D11 worlds skip stable topology validation after qualification and expose an
  explicit constraint-dirty hook for live edits. A local 10,000-particle/9,999-link chain with
  eight XPBD iterations measured a 0.133 ms median resident CPU submission across five warm
  ticks, with zero upload and zero readback; this is submission latency, not a GPU timestamp.
- Composable physics fields now share one authored contract across reference CPU, native SoA,
  provider GPU, and native D3D11. Qualified modes include directional/uniform gravity, gusting
  velocity-relative wind, inverse-square point gravity, attractor/repulsor/radial fields, vortex,
  continuous deterministic turbulence, linear/quadratic drag, and provider/native buoyancy.
  Controls include enable, inner/outer radius, falloff power, acceleration clamp, drag, gust,
  frequency, noise scale, seed, and ambient density. D3D11 keeps spatial field records resident;
  buoyancy remains provider/native until particle density joins the D3D particle layout.
- The provider-GPU neighbor stage now uses sorted spatial-hash cells and 27-cell local candidate
  expansion rather than an N-by-N distance matrix. It supports up to two million particles with
  an explicit eight-million-candidate density guard and reports candidate pressure in receipts.
- Sparse native/provider volume buffers now optionally retain neighbor topology, divergence, and
  Jacobi pressure arrays for velocity projection. Pressure iterations and projection strength are
  authored properties and default off for compatibility; regression scenes verify reduced
  divergence and reference/native/provider agreement.
- A synchronized local D3D11 field stress run covering 20,000 particles and four combined fields
  measured 1.075 ms for ten warm ticks plus final readback (0.107 ms/tick on that device).
- Native D3D11 mesh collision now compiles the canonical refittable triangle BVH into contiguous
  node bounds, integer child/leaf metadata, and leaf-ordered triangle vertices. A bounded 64-level
  compute traversal performs sphere/AABB rejection, closest-triangle contact, moving-surface
  friction, and restitution without CPU candidate queries; topology/refit signatures control
  resident uploads and deeper trees fail closed.
- Native D3D11 self-collision now uses a persistent multi-pass spatial hash: power-of-two bucket
  clearing, atomic particle insertion, exact 27-cell validation to reject hash collisions, and a
  race-free Jacobi correction into a scratch position buffer before device-local copyback. Local
  traversal is never silently truncated, pinned/frozen collision obstacles remain capability-gated,
  and the qualified world bound is two million particles. A synchronized sparse 10,000-particle
  stress run measured 19.766 ms for ten warm ticks plus final readback (1.977 ms/tick locally).

Still required before a production game-runtime claim:

- Native continuous self-contact/CCD, multilayer contact caching, parallel task-graph islands,
  and vectorized mesh candidate batches.
- Native D3D11 shaders for area/volume XPBD and material-neighbor broadphase; those stages
  currently run on the CuPy-compatible provider path and fall back to native CPU on D3D11.
- D3D11 material-neighbor hashing, indirect rendering,
  and cross-device determinism qualification.
- GPU-resident particle, constraint, collision, event, and indirect-render buffers.
- Production cloth self-contact/CCD, tearing, remeshing, multilayer friction, and wrinkle validation.
- Production sparse-fluid advection/pressure projection, combustion chemistry, and physically based volume renderer.
- Engine renderer integration for mesh particles, ribbons, beams, decals, lights, distortion, refraction, and volumes.
- Replication codecs, platform determinism qualification, memory pools, streaming simulation LOD, and stress baselines.
