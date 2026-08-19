# Tech Connector DCC and Game Engine Industry Readiness

Date: 2026-08-08

## Executive assessment

Tech Connector is a substantial DCC-and-engine vertical slice, not yet a general replacement for Maya, Blender, Houdini, Unreal Engine, or Unity. It has real retained scene data, modeling and rigging operations, federated DCC workflows, graph authoring, simulation, a native C++ runtime, Direct3D 11 presentation, and a validated Windows packaging path. Its strongest differentiator is the shared authoring/runtime contract across external DCCs. Its largest remaining gaps are production-scale qualification, renderer and platform breadth, deep specialist tooling, and ecosystem maturity.

This pass fixes the concrete correctness and UX defects found in the review and adds evidence where it was feasible. It does not relabel preview implementations as production-ready.

## Fixes completed in this pass

| Area | Defect or risk | Implemented boundary |
| --- | --- | --- |
| Document safety | Local mutations were not consistently reflected in the dirty revision | Successful mutating adaptive commands now finalize through one document controller. Read-only commands are excluded, existing undo checkpoints are not double-counted, viewport navigation and shot-guide edits mark the scene dirty, and lifecycle tests cover save, autosave, recovery, and close protection. |
| Component modeling UX | Vertex and Face modes were click-only; Edge mode and box selection were absent | Vertex, Edge, and Face support click selection. All three support marquee selection, additive/toggle modifiers, select-all, clear, visible face filtering, and an on-screen selection rectangle. F8/F9/F10 switch modes. |
| Picking architecture | Projection, topology, selection policy, and widget event handling were interleaved | Pure component-picking and document-finalization logic were extracted into focused modules. Projected mesh data is cached and invalidated from camera/geometry state rather than recomputed on every pick. |
| Accessibility | Important panels and modes lacked usable names, descriptions, tab order, and keyboard paths | Scene hierarchy, selected-object properties, viewport status, canvas, and timeline have accessible metadata. A deliberate tab sequence and keyboard-only component selection flow are regression tested. |
| User-action failures | Several save, restoration, timeline, and viewport-camera failures were swallowed | Nonfatal failures now enter a bounded diagnostic history, log context and traceback, and surface a status message for interactive failures. Benign teardown/disconnect failures remain low-noise. |
| Authored gameplay graphs | Keyed graph metadata, link serialization, and exposed movement operations did not reach the player | Metadata maps/lists compile correctly; graph links survive packaging; input-axis, velocity calculation, and actor velocity operations execute in the native runtime. |
| Scene interaction correctness | Component modes could fall through into paint; a shot-guide drag referenced an undefined value | Component modes cannot start paint strokes. Shot-guide drag now starts safely and is regression tested. |
| Player cooking | Copying the executable was treated as a successful build and copied assets were not verified | A package build now hashes every copied content asset against the runtime manifest, runs a two-frame headless player smoke test, requires the success marker, rejects graph errors, and records validation in `TC_PLAYER_BUILD.json`. |
| Runtime profiling | Raw mixed JSON and graph text was difficult to consume | Validation now reports frame, graph, physics, and GPU average/p95/maximum timings. Successful graph trace is separated from actual diagnostics. |
| Renderer UX and claims | Backend choice and support were implicit | `tc_player` accepts `--renderer`, `--renderer-capabilities`, `--require-renderer`, and `--help`. D3D11 reports its actual capabilities. D3D12, Vulkan, and Metal explicitly report unavailable and return a failure code when queried/required. Invalid names fail with a clear message. |
| Platform claims | Headless portability could be confused with graphical parity | Capability receipts state Windows/D3D11 graphical support and headless-only Linux/macOS builds. No Vulkan, Metal, console, or mobile claim is made. |
| Native build | A C source file lived in a C++-only CMake project, Eigen registered more than 900 irrelevant upstream tests, and renderer capabilities lacked direct native tests | CMake declares C and C++, dependency tests are excluded from the project CTest inventory, and the three TC native suites build and pass under MSVC. |
| Python compatibility | A small group of modules evaluated modern union annotations during import under Python 3.9 | Postponed annotation evaluation was added to every affected module, allowing the default Python 3.9 environment to collect and run the full suite. |
| Dependency disclosure | Native-looking scene import obscured a Blender worker dependency | Capability output identifies the external Blender converter, executable/worker requirement, supported dimensions, and limitations. |

## Current feature and UX position

### DCC application

Tech Connector now meets a credible vertical-slice baseline for document safety, object/component interaction, command discoverability, keyboard access, basic retained modeling/rigging/animation workflows, source restoration, and cross-host receipts. Compared with Maya or Blender, it still lacks the breadth and refinement expected in dense production modeling, sculpting, UV editing, animation curves, graph debugging, workspace customization, color management, and large-scene interaction.

The scene widget is materially safer and more modular than before, but it remains a large orchestration surface. The new picker, lifecycle, and performance services establish extraction boundaries; they are not evidence that the entire widget has been decomposed.

### Game engine and player

The authored scene-to-native-player route is real: scene data compiles to a bounded runtime manifest, gameplay graph links execute, assets are copied and hash-checked, the C++ runtime loads the package, and the package emits frame profiles. Compared with Unreal Engine or Unity, Tech Connector still lacks production renderer breadth, mature shader/material authoring, navigation tooling, networking qualification, platform SDK integration, console/mobile cooking, hot-reload depth, crash telemetry, and shipped-title evidence.

The renderer abstraction is now inspectable and fail-closed, but only Direct3D 11 presentation is implemented. This pass intentionally did not create superficial Vulkan/Metal stubs and call them platform support.

## Performance and qualification evidence

The new component-picking baseline exercises 50,000 vertices, 99,102 triangles, and 149,101 unique edges, including edge-index construction, point picking, and marquee selection under a 5-second regression budget. This is useful regression evidence for medium-size authoring meshes. It is not a multi-million-component viewport qualification and does not prove stable interactive frame rates on production scenes.

Runtime package validation exercises a real compiled Windows player for two headless frames. The latest acceptance run produced:

- exit code 0 and the `TC_PLAYER_OK` success marker;
- 5 entities and 7 graph operations with no compile warnings;
- 2 frame profiles;
- approximately 0.111 ms average headless frame time in that tiny acceptance scene;
- copied-asset SHA-256 verification with no mismatches;
- no diagnostic errors, with successful graph trace retained separately.

Headless timing is a correctness smoke signal, not a rendering benchmark.

## Remaining gaps, prioritized

### P0 before a production-ready claim

1. Qualify representative production scenes: multi-million component meshes, thousands of objects, long animation takes, large textures, heavy graphs, autosave during load, and memory-pressure recovery.
2. Add golden visual/output suites for modeling, rigging, animation, import/export, cooking, and D3D11 rendering, with tolerance policies and artifact retention.
3. Add crash/hang recovery and corruption tests around scene writes, package writes, worker cancellation, plugin failures, GPU device loss, and interrupted builds.
4. Establish supported OS/DCC/version matrices in CI with real host readback rather than contract-only tests.
5. Finish release engineering: signed artifacts, reproducible dependency locks, upgrade/migration policy, installer repair/uninstall, symbol archives, and release rollback.

### P1 for industry-competitive workflows

1. Continue decomposing the main DCC widget into selection, timeline, paint, camera, diagnostics, host-session, and command controllers with stable public contracts.
2. Add a real curve editor/dope-sheet workflow, layered animation conflict UX, retargeting UI, pose libraries, animation baking, and dense rig performance tests.
3. Expand component editing with loop/ring selection, soft selection, transform pivots/orientations, snapping, UV tools, topology diagnostics, symmetry, and non-destructive modifier history.
4. Add shader/material graph authoring, shader compilation diagnostics, pipeline-state caching, texture streaming, occlusion/culling qualification, and render-capture tooling.
5. Add runtime graph breakpoints, stepping, watch values, entity/component inspection, trace filtering, capture comparison, and performance-budget gates.
6. Add navigation mesh authoring, AI debugging, multiplayer replication/rollback evidence, save migration, localization, input rebinding, and accessibility settings in the player.

### P2 platform and ecosystem breadth

1. Implement and qualify a second graphical backend before claiming portability. Vulkan is the likely Windows/Linux candidate; Metal requires a native macOS implementation and CI hardware.
2. Add Linux/macOS graphical packaging only after windowing, input, audio, renderer, installer, and crash-reporting paths are native and tested.
3. Define plugin ABI/versioning, isolation, permissions, compatibility testing, package signing, and a supported extension SDK.
4. Build telemetry, issue reproduction bundles, automated performance dashboards, documentation search, tutorials, templates, and migration guides.

## Release boundary

The capability maturity audit remains authoritative. Catalog presence, a local executor, or an interactive entry point must not be marketed as production qualification. Production claims require native execution, transfer/readback, recovery, representative performance, golden artifacts, stress evidence, and platform qualification. Features outside the verified Windows/D3D11 player and explicitly qualified DCC workflows should remain labeled preview, experimental, translated, or delegated.

## Verification record

- Python compile check: passed under the default Python 3.9 interpreter.
- Full Python regression suite: **365 passed** in 27.07 seconds under CPython 3.14.6 using a fresh workspace-owned pytest temp root.
- Native MSVC build: `tc_runtime_core_tests`, `tc_gpu_renderer_tests`, and `tc_player` built successfully.
- Native runtime test executable: passed, exit code 0.
- Native renderer capability test executable: passed, exit code 0.
- Player renderer CLI: D3D11 available/exit 0; Vulkan unavailable/exit 4; invalid backend/exit 1; help/exit 0.
- End-to-end Windows package build: passed, two frame profiles, exit code 0, asset hashes verified, no compile warnings.
- Build-system warnings are limited to pinned Eigen deprecation/optional dependency discovery and a sandbox-denied user registry package registration; compilation and tests succeed.
