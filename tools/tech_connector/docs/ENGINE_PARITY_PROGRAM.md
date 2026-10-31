# Tech Connector Engine Parity Program

## Objective and claim boundary

Deliver the everyday production workflows that teams expect from Unreal Engine
and Unity, then surpass them in cross-DCC automation, inspectability, and safe
iteration. Parity is judged by completed projects and reproducible evidence,
not by asset type counts, API names, or a successful demo scene.

This program extends the [asset system audit](TC_ENGINE_ASSET_SYSTEM_PLAN.md).
The audit remains the source for current implementation status. The public
`api.kingdom.capability_report()` exposes the live registry and editor operation
coverage; it explicitly separates runtime availability from production proof.

## Current baseline (2026-10-16)

- 64 built-in asset types: 22 runtime-ready, 32 authoring-preview, 10
  experimental, and none production-ready in the registry.
- The editor contract declares more than 250 operations across asset, content,
  level, world, animation, material, physics, audio, sequence, and gameplay
  workflows. The capability report checks that declared handlers are callable.
- The native player has Windows/D3D11 graphical presentation and a verified
  package smoke test. Other graphical backends and target platforms need native
  implementation and hardware evidence before support is claimed.
- UI/2D, networked gameplay, resumable builds, large-world runtime stress,
  platform breadth, and production renderer qualification remain the largest
  parity gaps.

### Progress (2026-10-17)

- UI Document is the 65th built-in asset type, registered as authoring-preview.
  The current registry has 22 runtime-ready, 33 authoring-preview, 10
  experimental, and no production-ready types.
- The first UI document slice supports create/edit/validate, a visual widget
  hierarchy, anchor-based desktop/mobile preview, asset references, Python API
  calls, and a derived layout preview. Packaged player rendering, responsive
  constraints beyond point anchors, rich text, localization, and accessibility
  testing remain open.
- Playable-project qualification now requires a packaged Windows/D3D11 windowed
  run, GPU-backed frame profiles, and a rendered BMP capture in addition to the
  existing deterministic cook, integrity, and headless checks. The
  `playable_sandbox/standard` template passed a local eight-frame run on
  2026-10-17. This proves a small graphical package path, not sustained frame
  rate, hardware breadth, visual correctness across scenes, or completion of
  the third-person acceptance project.
- The first live qualification attempt exposed a starter Skeleton cook failure:
  retarget-pose metadata keys were interpreted as bone names. The validation
  contract was corrected and regression-tested before the passing run.
- Third-person exploration now has a reproducible API-to-package acceptance
  command in `game_engine.integration.third_person_acceptance_service`. A local
  600-frame Windows/D3D11 run (60 warmup, 540 measured) passed deterministic
  compilation, asset cooking and integrity, headless and windowed execution,
  skinned character rendering, the configured frame/GPU timing budgets,
  intentional content-corruption detection/restoration, and reuse of a compiled
  package checkpoint. It does not yet simulate an interrupted worker stage.
  The reported steady-state p95 was 0.0792 ms for runtime `frame_ms`
  and 2.78214 ms for renderer `gpu_ms` on this small local scene. These are
  subsystem timings, not end-to-end display latency or a production-scale
  hardware benchmark.
- That run caught a package path mismatch: copied assets were written as
  package-root-relative paths while the native player resolved them relative
  to `Content/main.tcruntime`, causing a fallback cube instead of the character.
  Packaged asset paths are now manifest-relative, and both the third-person and
  sandbox qualification gates require actual skinned draw evidence. The earlier
  sandbox-only graphical pass should not be used as character-rendering proof;
  it was rerun after the fix.
- The full third-person acceptance project remains **partial**. Import/reimport,
  animation and rig gameplay, input rebinding, runtime UI, audio, save/load
  migration, interactive debugging, golden-image review, and representative
  scene/hardware stress still need end-to-end receipts.

Run the technical baseline on Windows with a built player:

```powershell
python -m tech_connector.game_engine.integration.third_person_acceptance_service --output <output-directory> --player <tc_player.exe> --variant exploration --frames 600 --warmup-frames 60
```

Add `--dcc-fbx <rigged-character.fbx>` to include the isolated skeletal
import/reimport gate; the source file is read but never modified.

The command writes `third_person_exploration_acceptance.json` and retains the
package, profiles, and captured frame under its run directory. `partial` means
the technical baseline passed but the complete game acceptance did not.

### Progress (2026-10-19)

- The packaged player now emits Player position and active animation in its
  per-frame profile, and accepts `--verify-save-roundtrip <path>` for a headless
  save/load check against a freshly loaded runtime. This diagnostic option does
  not turn the headless benchmark into a graphical performance measurement.
- The 600-frame third-person exploration run now proves scripted movement,
  observed locomotion transitions (`tc_walk_right`, `tc_walk`, `tc_run`, and
  `tc_idle`), and restoration of Player position from a version-2 save. All
  existing package, graphical, skinning, timing, and asset-integrity checks also
  passed. The receipt remains **partial**: it does not prove save migration,
  corrupted-save handling, interactive input rebinding, or full animation/rig
  gameplay.
- The next acceptance slice routes a topology-preserving mannequin OBJ change
  through public `import_asset`/`reimport_asset` calls, binds the imported mesh
  to the Player Level actor, cooks it, and verifies its changed hash plus skinned
  rendering in the packaged player. This is mesh reimport, not Maya skeletal
  interchange or full character-rig reimport.
- An opt-in windowed scripted-input run now proves movement and locomotion
  transitions while D3D11 renders. Ordinary keyboard controls remain separate;
  this does not yet qualify rebinding or all device types. A silent PCM cue is
  imported and played by the packaged XAudio2 mixer, with a structured success
  or failure row in the player profile. Broader audio authoring and device
  recovery remain open.
- The save probe now verifies one concrete migration route (v1 position-only to
  v2 save), rejects an unsupported/corrupt header without changing Player state,
  and retains the migrated receipt. Interrupted writes, multiple-version save
  evolution, and user-facing recovery are not yet qualified.
- An optional `--stress-actors 256` acceptance run drew 260 renderables for 600
  frames on one Windows/D3D11 machine and passed the configured timing checks.
  These render-only cubes are a synthetic scale probe, not representative
  streaming, texture, animation, or multi-hardware stress.
- The player now writes an atomic checksum-protected v3 save, preserves a prior
  save as a backup, and loads that backup after a simulated torn primary write.
  It still accepts v1/v2 files and verifies v1-to-v3 and v2-to-v3 migrations. More migration
  versions, disk-full failures, and recovery UX remain unqualified.
- A saved UI Document now compiles panel/text/button widgets into the runtime
  manifest. The D3D11 player draws them on the swap-chain surface, and a
  packaged scripted click exercises the Save button. Image widgets,
  localization, accessibility, flexible layout and device coverage remain open.
- The packaged windowed player now reads keyboard bindings from the runtime
  manifest and routes Windows key-down/up messages through them. The acceptance
  project rebinds movement from D to L and drives that path in its windowed run;
  controller mapping, user-facing rebinding controls, and conflict handling
  remain open.
- F9 in the packaged player writes an entity/transform/animation inspection
  snapshot; F10 pauses/resumes simulation and F11 single-steps while paused.
  `--break-frame N` pauses automatically after tick N for repeatable inspection.
  A paused in-app inspector shows the frame, entity/event counts, Player position,
  and debugger controls; it refreshes after a single step. The D3D11 scripted
  acceptance verifies pause, inspector capture, snapshot, one step, and resume.
  A visual landmark probe also checks the captured HUD panel and button against
  the scene sky. Editable entity/graph inspection, conditional breakpoints,
  and a reviewed multi-device golden-image library remain open.
- The acceptance cue is now a short non-silent PCM tone with a fade. The receipt
  checks its source samples and the packaged XAudio2 playback event; audible
  output quality, device switches, and failure recovery are not yet measured.
- A 600-frame, 256-prop local run passed all 31 then-current technical checks
  (540 measured frames, 260 minimum draw calls, p95 runtime frame 0.105 ms and
  p95 renderer GPU 1.55524 ms). The host reports an RTX 3060 Ti. The report remains
  `partial` because these are subsystem timings on one synthetic scene and one
  GPU, not representative hardware or full third-person game qualification.
- An optional `--dcc-fbx <path>` gate now exercises a user-provided skeletal FBX
  through Blender-backed skin extraction and the public asset import/reimport
  API. With `SKM_Test.fbx`, a disposable source revision changed one vertex
  while preserving 280 bone names, 29,094 vertices, and 100,404 skin influences;
  both skin contracts validated and the original file stayed unchanged. A
  separate D3D11 package also rendered its 58,184-triangle skinned mesh with a
  valid CPU-skin fallback and a visible-color pixel check. The source contains
  no animation clips. An in-place walk has since been retargeted from Godot's
  CC-BY TPS demo to the unchanged `SKM_Test.fbx` source. The baked FBX retains
  all 280 bones, 29,094 vertices, 58,184 triangles, and 100,404 influences;
  reimport exposes a 31-frame pose cache and valid skin contract, with visibly
  different front/side pose renders. This proves DCC retarget and interchange,
  but not timed playback of that DCC clip in the packaged player. The authored
  animation still needs to drive the third-person runtime actor before this
  portion of acceptance is complete.
- The combined 600-frame run with `--dcc-fbx` passed all 33 technical checks;
  its main stress package measured p95 renderer GPU 2.60464 ms. The separate
  imported-character package passed asset integrity and visible skin-render
  checks. Full acceptance remains `partial` for the remaining gameplay,
  accessibility, device, debugger, and hardware-matrix gates.

## Acceptance projects

Each project must use the public editor API and the normal UI, cook from a clean
checkout, run in a packaged player, and produce machine-readable receipts with
asset-linked failures. Freeze representative hardware and project fixtures for
repeatable comparisons.

| Project | Required end-to-end proof |
| --- | --- |
| Third-person action | Import and reimport a character, author animation, rig, input, materials, effects, audio, UI and save state; play, debug and ship. |
| 2D game | Sprite/atlas/tilemap workflow, camera and collision, responsive UI, localization, input rebinding, accessibility options and a packaged build. |
| Multiplayer arena | Dedicated server, client join/rejoin, ownership, replication, prediction/rollback, latency and packet-loss simulation, profiling and deterministic replay. |
| Large world | Streaming cells/data layers, terrain/foliage, HLOD, navigation, memory budgets, travel without visible stalls and recovery from missing content. |
| Updated live game | Versioned content bundles, remote or local update, dependency validation, rollback, save migration, and a repeatable release build. |

The project is incomplete when a required action only works through an internal
script, when the editor and API serialize different data, or when a packaged
player does not exercise the result.

## Workstreams and release gates

### Gate 1: dependable single-player production path

1. Complete UI documents, widgets, sprites/atlases, tilemaps, localization,
   captions, accessible controls, and input rebinding with create/edit/preview/
   cook/runtime/API paths.
2. Make cook and package jobs resumable and cancellable. Report the exact asset,
   dependency, platform, phase, size, time, and recovery action for each failure.
3. Establish renderer golden scenes, shader and pipeline caches, GPU capture,
   frame/memory budgets, device-loss recovery, and project-scale stress on the
   supported D3D11 path.
4. Add reproducible save migration, crash diagnostics, graph/entity inspection,
   frame capture, profiling comparison, and automated project tests.

Gate passes when the third-person and 2D acceptance projects build and run from
clean source on the declared Windows hardware matrix, with retained visual,
performance, recovery, and package receipts.

### Gate 2: multiplayer, large worlds, and platform breadth

1. Complete authority, replication, prediction, rollback, dedicated-server,
   session, and network diagnostics workflows. Existing physics packet/rollback
   helpers are a foundation; they are not a complete game netcode stack.
2. Prove world streaming, data layers, HLOD, navigation, and content updates
   under representative object counts and memory pressure.
3. Implement a second graphical backend, then qualify windowing, input, audio,
   rendering, installation, crash reporting, and builds on each new platform.
   Do not infer graphics support from a headless build.

Gate passes when the multiplayer, large-world, and updated-game projects pass
network, stress, recovery, and platform tests in packaged players.

### Gate 3: surpass on workflow

1. Let a user move assets and authored intent between Maya, Blender, Unreal,
   Unity, and Tech Connector with stable IDs, diff previews, provenance, conflict
   handling, and reversible transactions.
2. Make every assisted operation produce a plan, explicit target, validation,
   changed-asset list, and recovery receipt. Measure time and errors against the
   equivalent manual workflow on the same fixture.
3. Give each asset and engine feature one discoverable place for Create, Edit,
   Preview, Cook, Runtime, Ship, API, platform support, limitations, and proof.
   Keep familiar labels visible beside product names such as Garden and Kingdom.

Gate passes only when the cross-DCC and assisted workflows beat the baseline on
the same acceptance projects without reducing correctness or recoverability.

## Tracking rules

- Track each feature through `planned`, `authoring-preview`, `runtime-ready`,
  `production-ready`, and `qualified-on-platform`. A feature cannot skip the
  required tests and receipts by adding a registry descriptor.
- Keep parity claims scoped to the exact workflow, engine version, platform,
  project scale, and hardware on which they were verified.
- Review the current public competitor documentation when refreshing the
  benchmark: [Unreal tools](https://dev.epicgames.com/documentation/en-us/unreal-engine/tools-and-editors-in-unreal-engine),
  [Unreal World Partition](https://dev.epicgames.com/documentation/unreal-engine/world-partition-in-unreal-engine),
  and [Unity render pipeline feature comparison](https://docs.unity.com/en-us/engine/6000.3/manual/render-pipelines/choose-a-render-pipeline/feature-comparison).
