# TC Procedural Content Engine

## Product Direction

TC procedural content is one editable source graph that can run in The Entire
Scene, stream in the TC game runtime, translate to another DCC or engine, or bake
to deterministic geometry and instance data. A target-specific graph is an
adapter output, not the source of truth.

The design combines four useful models:

- Unreal PCG: spatial data, attributes, partitioned and hierarchical runtime generation.
- Blender Geometry Nodes: artist-friendly fields, repeat/simulation zones, tools, and inspection.
- Houdini SOPs and PDG: non-destructive geometry recipes plus dependency-aware distributed work.
- Unity and Godot: portable runtime data with efficient spline, terrain, jobs, and instancing adapters.

## Implemented Foundation

- Versioned `tc.procedural_graph.v1` graph and stable node IDs.
- Deterministic point and instance payloads with arbitrary attributes.
- Native point bounds, color, density, steepness, seed, transform, and metadata.
- Grid, bounded scatter, spline sample, transform, repeat, attribute noise,
  attribute filter, weighted asset selection, merge, instance, and output nodes.
- Heightfields with bilinear elevation/layer sampling, normals, slope, projection,
  painted masks, polygon set masks, and spatial-hash neighborhood queries.
- Deterministic multi-octave terrain, moisture/temperature layers, and
  mass-preserving thermal erosion.
- Biome species rules for elevation, slope, climate, density, spacing, scale,
  tags, and hierarchical runtime-grid assignment.
- Bounded shape grammar, weighted modular assets, spline arc-length placement,
  tangent orientation, and shared road/fence/rail/pipe/facade layout contracts.
- Procedural mesh payloads using TC's transactional topology model, with cube
  and grid primitives, transforms, face extrusion, triangulation, and edit receipts.
- Content-addressed incremental node cooking.
- Per-node timings, counts, cache state, warnings, and content fingerprints.
- Editable graph persistence and last-cook receipts inside `.tcscene` metadata.
- Native graph or hybrid bake manifests for Unreal, Blender, Houdini, Unity, and Godot.
- Hierarchical spatial chunks with stable IDs and no duplicated instances.
- Player, camera, or tool generation sources with distance/direction priority.
- Per-frame generation budgets, parallel limits, pooling metadata, deferral, and cleanup.
- Adaptive commands for UI, API, and chat entry points.
- PDG-style work-item graphs with inherited attributes, fan-out, fan-in,
  partitions, wedges, parallel local cooking, diagnostics, and cache reuse.

## Next Capability Blocks

### Spatial Data And Rules

- Explicit mesh surface, volume, SDF, point-cloud, and attribute-set types.
- Union, intersection, difference, projection, signed-distance, raycast, proximity,
  occlusion, and collision queries beyond the implemented sampled spatial masks.
- Masks from texture, vertex color, material, biome, landscape layer, camera,
  volume, distance, flow, weather, gameplay tags, and painted TC maps.
- Branches, switches, general loops, subgraphs, feedback, and reusable graph assets.
- Parameter presets, exposed controls, graph variants, and deterministic seed mutation.

### Geometry And Materials

- Field evaluation across vertex, edge, face, curve, volume, and instance domains.
- Additional primitives, curve, sweep, loft, revolve, inset, bevel, boolean,
  remesh, retopology, subdivision, deformation, UV, normal, and material nodes.
- SDF and voxel workflows for caves, terrain carving, erosion, fracture, and meshing.
- Realize-instances controls, material variants, collision generation, LOD/HLOD,
  virtualized geometry, impostors, and runtime platform tiers.
- Simulation and repeat zones with cache controls and explicit state inspection.

### World Building

- Tiled terrain, sculpt layers, hydraulic/flow erosion, rivers, lakes, oceans, cliffs, caves, and coastlines.
- Advanced biome ecology with competition, succession, seasons, weather, fire,
  flooding, snow, mud, and gameplay-driven changes.
- Spline network intersections, junction meshes, traffic lanes, sidewalks, and utility connectivity.
- Shape-grammar buildings, interiors, lots, cities, settlements, dungeons, and quests.
- Navigation, spawn, encounter, cover, traversal, audio, lighting, and gameplay-tag outputs.
- World-partition/data-layer equivalents, origin shifting, chunk persistence,
  deterministic multiplayer authority, and save-game deltas.

### Runtime And Scale

- Actual asynchronous worker execution behind the existing scheduler contract.
- Frustum and occlusion priority, predictive generation, cancellation, chunk pooling,
  memory/VRAM budgets, HLOD integration, and hitch telemetry.
- CPU, SIMD/job, GPU-compute, and server-authoritative execution backends.
- Persistent chunk caches, network replication, rollback, and deterministic verification.
- Runtime parameter overrides that dirty only affected cells and graph dependencies.

### Procedural Dependency Graph

- Persistent batches, dynamic tasks, artifact typing, and resumable task state.
- Variation galleries with comparable metrics and approval state on top of implemented wedges.
- Local process, persistent worker, farm, and cloud schedulers.
- Dirty propagation, partial recook, checkpoints, retries, cancellation, logs, and provenance.
- Geometry, simulation, render, ML, import/export, validation, and packaging task nodes.

### Target Adapters

- Unreal plugin creation/readback for PCG graphs, PCG data assets, runtime generation,
  World Partition, Data Layers, HLOD, Landscape, splines, and shape grammar.
- Unity importer/runtime using Splines, Terrain Tools, Burst/Jobs, Entities Graphics,
  GPU instancing, Addressables, and scene streaming where installed.
- Godot importer/runtime using Curve3D, FastNoiseLite, ArrayMesh/SurfaceTool,
  MultiMeshInstance3D, resources, scenes, and threaded CPU generation.
- Blender Geometry Nodes and Houdini SOP/PDG graph creation with parameter,
  attribute, instance, cache, and output readback.
- USD point instancers, OpenVDB, glTF, FBX, Alembic, textures, and baked mesh fallbacks.

## UX Requirements

- Graph, viewport, hierarchy, spreadsheet, profiling, and warnings stay synchronized.
- Every node exposes useful handles or gizmos directly in the viewport where applicable.
- Preview quality, region-of-interest, freeze, bypass, solo, compare, and bake controls.
- Users can begin from an artist task such as "scatter this forest" without building
  infrastructure nodes manually, then open and edit the generated graph.
- Chat, Python API, toolbar actions, and graph editing invoke the same commands.
- Every generated object explains its graph, node, seed, source asset, cell, and transfer state.

## Reference Baselines

- Unreal PCG data types, nodes, hierarchical generation, runtime generation, and biome examples.
- Blender Geometry Nodes attributes, fields, instances, repeat/simulation zones, baking, and inspection.
- Houdini SOP procedural modeling and PDG/TOP dependency scheduling.
- Unity Splines and Terrain Tools, plus job-oriented runtime adapters.
- Godot procedural geometry APIs and MultiMeshInstance3D instancing.
