# Tech Connector game engine

This package contains the headless scene-authoring and runtime systems. It is
safe to use without constructing the desktop UI.

- `assets/` — asset database and collision cooking.
- `authoring/` — rigs, procedural tools, graph programs, and world authoring.
- `deformation/` — skinning, anatomy, weight maps, and deformation contracts.
- `integration/` — DCC bridges, viewer commands, host policy, and transfer.
- `rendering/` — materials, lighting, and upscaling contracts.
- `runtime/` — graph, simulation, geometry, build, and console runtimes.
- `scene/` — coordinate spaces, conversion, USD/FBX, and scene deltas.

Qt editor surfaces live in `tech_connector.ui.game_engine`. DCC-connected
scene presentation lives in `tech_connector.ui.dcc_viewer`.

`tech_connector.engine` is intentionally separate: it is the AI request engine,
not the game engine.

## Audio asset pipeline

The portable audio slice treats source media as immutable and stores import,
streaming, compression, looping, and normalization settings in asset metadata.
First-class Sound Cue, Audio Mixer, Attenuation, and Reverb assets expose typed
editor pages, deterministic validation/cooking, dependency tracking, and the
same operations through `TCEditorAPI`. Unreal Sound Cue/Attenuation exports and
Unity AudioSource/AudioMixer-style payloads can be converted into the native
asset vocabulary while preserving unknown source extensions for later adapters.

```python
from tech_connector.game_engine.assets import TCEditorAPI

editor = TCEditorAPI("C:/Game")
attenuation = editor.create_audio_attenuation("World3D")
cue = editor.create_sound_cue(
    "Impact",
    properties={"attenuation_asset_id": attenuation.asset_id},
)
editor.validate_audio_asset(cue.asset_id)
editor.cook_audio_asset(cue.asset_id, platform="windows", quality="high")
```

## Typed gameplay foundation

Project Settings, Data Schema, Struct, Enum, Data Asset, Data Table, Component
Archetype, and Character Definition are first-class authored assets. Schemas can
inherit fields; consumers are validated against resolved field types; component
hierarchies retain stable IDs; and every asset records UUID dependencies before
producing deterministic runtime data. The dedicated Project Settings, field,
and component editors use the same `TCEditorAPI` operations available to Python.

Unreal Data Asset reflection payloads and Unity ScriptableObject payloads can be
converted into native schemas plus typed data assets. Unknown engine behavior is
not silently represented as equivalent runtime logic.

## Runtime production-readiness

Simulation assets compile through one backend-independent IR. Runtime instances
now expose explicit lifecycle state, fixed-step command scheduling, bounded
history, rollback checkpoints, deterministic cache capture, authored-asset
fingerprints, per-tick state hashes, actual backend/residency telemetry, and an
evidence-backed qualification report.

```python
from tech_connector.game_engine.runtime import engine

configured = engine.create_effect("sparks", target="desktop")
runtime = configured.runtime
runtime.enable_cache()
for _ in range(60):
    runtime.advance(runtime.fixed_dt)

qualification = engine.qualify_runtime(
    runtime, ticks=30, repeats=3, minimum_performance_samples=30,
)
```

`qualified` is intentionally strict: a valid graph or available GPU does not by
itself prove production readiness. Qualification requires an executable backend,
bounded runtime state, required outputs, independent deterministic replays, and
measured p95 performance evidence. Compiled and actual execution backends are
reported separately so a domain-limited GPU path cannot hide a CPU fallback.

The largest remaining engine programs are broader GPU domain coverage and
native graphics-API shared handles, shader/pipeline compilation, world
partition/asset streaming, job-system scheduling,
networked simulation qualification under latency/loss, save migration, and
golden-scene qualification across supported hardware.

### Resident rendering and multiphysics

`build_simulation_render_stream()` exposes particle positions, velocities,
radii, and alive masks from persistent native or provider-owned GPU buffers.
Receipts distinguish source-buffer reuse, consumer upload, forced readback, and
true end-to-end zero-copy. The current Qt Quick consumer can read native host
SoA state directly but still uploads geometry; GPU device-handle sharing remains
an explicit qualification blocker.

`build_fx_render_graph()` now compiles the portable scheduling layer needed by
that handoff: compute culling/compaction, indirect draw preparation,
transparency and refraction, temporal reconstruction, presentation, inferred
RAW/WAR/WAW barriers, graphics/compute/copy queue synchronization, and bounded
transient-resource aliasing. When an end-to-end shared resource is unavailable,
the graph inserts an explicit copy pass and records why; it does not report the
fallback as zero-copy. Native D3D12/Vulkan/Metal resource import, descriptor
binding, shader compilation, and command-list execution remain backend work and
must qualify independently before the shared-resource blocker can be cleared.

### Media texture sources

Portable material texture slots accept still images, animated images (GIF/APNG),
numbered image sequences (`####` or `%04d` patterns), and video sources through
`MediaTextureSource`. Source type can be inferred from
the extension or authored explicitly. Each animated slot preserves autoplay,
looping, playback rate, start/end trim, mute, frame-rate intent, synchronization
mode, and fallback-frame policy. The Qt Quick 3D viewer binds animated media via
`Texture.sourceItem` for regular and skinned materials; static images continue
through the existing mipmapped file-texture path. Video decode and hardware
acceleration remain codec/platform dependent and are reported by runtime
capability and qualification receipts.

Timeline-synchronized sources now seek from the authoritative viewer frame and
FPS, so scrubbing, offline rendering, and export do not depend on decoder clock
drift. Real-time and manual clock modes remain available for live displays.
Concurrent animated sources and video decoders are bounded by a deterministic
residency plan; over-budget slots are reported and deferred instead of silently
creating unbounded decoder work.

### Procedural shader graphs

`procedural_shader_service` defines a versioned, portable graph vocabulary for
coordinates and animation, linear/radial/angular ramps, editable color ramps,
checker/brick/dot/hex/wave patterns, value and gradient noise, Voronoi/Worley,
fBm, turbulence, ridged fractals, math/remap/mask nodes, layer blends, color
adjustment, Fresnel, height-to-normal, and triplanar intent. Graph validation
detects missing references, cycles, excessive octaves, and estimated cost before
rendering. Built-in ramp, marble, lava, electric-cell, ripple, cloud, brick, and
hologram presets are available from the selected-material controls.

The Qt viewport now lowers supported graphs into graph-specific executable
`CustomMaterial` fragment shaders. Sources are content-addressed and cached;
Qt Quick 3D's RHI compiles and caches the backend pipeline for the active
D3D/Vulkan/Metal/OpenGL renderer. Timeline animation changes a GPU uniform and
does not rebake pixels. The bounded deterministic RGBA preview remains an
explicit recovery path for nodes that the native Qt lowering library does not
yet support. GLSL/HLSL/MaterialX interchange manifests remain separate and are
not mislabeled as directly executable in another host without its native graph
translator.

`compile_multiphysics_coupling()` adds ordered pre-solve, contact, exchange, and
post-solve stages for fields, particles, fluids, cloth, soft bodies, rigid
bodies, volumes, effects, and reactive surfaces. Exchange buffers are bounded.
If a selected backend lacks any required coupling kernel, the runtime currently
falls back for the whole tick; hybrid per-stage device scheduling is not yet
claimed or hidden.
