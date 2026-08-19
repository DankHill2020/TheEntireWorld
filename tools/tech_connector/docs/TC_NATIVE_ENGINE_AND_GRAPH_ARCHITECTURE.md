# TC Native Engine And Graph Architecture

## Language Responsibilities

TC uses languages by responsibility rather than forcing the entire product into
one toolchain:

- C++23 owns the shipping frame loop, renderer, scene runtime, animation,
  deformation, simulation, audio, platform services, and native DCC/engine plug-ins.
- Rust owns defensive asset ingestion, dependency analysis, cooking, packaging,
  downloads, and parallel build services where memory-safe concurrency has the
  greatest leverage.
- Python owns editor automation, chat, pipelines, DCC workflows, tests, and rapid
  reference implementations. Python is not required by the shipping frame loop.
- A versioned C ABI connects native modules and generated bindings. It uses opaque
  handles, plain data, explicit ownership, structured errors, and no cross-boundary
  exceptions or panics.

## One Program, Two Editors

Graph View and Code View edit one `EngineGraphProgram`. They are not separate
assets and one does not hide an unrelated implementation behind a visual wrapper.

- A graph edit regenerates deterministic, readable Python.
- A supported Python edit reparses into the same nodes and connections.
- Stable `tc-node` identities preserve layout, comments, selection, breakpoints,
  profiling history, and source-control diffs.
- Ordinary Python variables represent graph data connections.
- Invalid code keeps the last valid graph visible and reports the exact line and
  reason; it never silently discards nodes.
- Code outside the reversible language subset must be placed in a registered
  function node. The graph shows that boundary explicitly.

The serialized scene entry contains the canonical graph, synchronized source,
and a native manifest. The native manifest is what the future C++ runtime consumes;
the Python source remains useful for authoring, preview execution, automation, and
human-readable review.

## Graph Families

The shared program model grows through typed operation definitions rather than
new incompatible graph formats:

- Gameplay events and actions
- Actor components and reusable functions
- Input and movement
- Animation and rig evaluation
- State machines and animation trees
- Behavior, dialogue, objectives, and world intelligence
- Materials, shaders, and render passes
- Effects, simulation, and procedural generation
- UI and accessibility behavior
- Audio and music logic
- Networking, authority, prediction, and replication

Specialized editors may arrange these operations differently, but they compile to
the same program and operation contracts.

## Action Search

The action menu opens in `Context Sensitive` mode. Results are filtered using the
current graph family, owner type, scene selection, available project capabilities,
network authority, and the type of any pin being dragged. Turning context sensitivity
off searches the complete global operation library.

Global results are not opaque: incompatible actions state why they do not apply to
the current graph or selection. Dragging from an output offers consumers of that
value type; dragging from an input offers compatible producers. Search covers friendly
names, descriptions, categories, property labels, aliases, and stable operation keys.

## Friendly Properties

Every exposed input has a stable internal key plus user-facing metadata:

- Display name
- Plain-language description
- Type and default
- Units and valid range
- Category and advanced status
- Search aliases and migration aliases

The Inspector, tooltips, documentation, autocomplete, chat, undo text, and native
bindings all read the same metadata. Internal names such as
`cloth_stretch_compliance` may remain stable in files while users see a name such
as `Stretch Flexibility` and a description of its visible effect.

## Compilation Ladder

1. Validate node identity, types, links, control flow, authority, and side effects.
2. Produce deterministic Python for editor execution and inspection.
3. Produce `tech_connector.native_graph_manifest.v1` for the C++ runtime.
4. Resolve operation keys to native function-table entries through `tc_graph_c_v1`.
5. Compile hot paths to native execution groups and retain debug-to-source maps.
6. Hot-swap compatible graph revisions into a running playtest.

The native compiler must preserve node IDs in diagnostics and profiling receipts so
an expensive C++ operation can highlight the exact node and source line that owns it.

## Reference Runtime Behavior

The Python reference runtime now executes the same native manifest contract used for
C++ parity work. It is an executable specification, test runtime, and editor preview;
it is not intended to replace the shipping native frame loop.

- Input actions are read from the active runtime context and clamped to their valid range.
- Movement normalizes directional input, observes actor velocity, and applies acceleration
  over the fixed simulation step before committing actor state.
- Actor mutation and gameplay events use staged state. If a later node fails, times out,
  exceeds a budget, is canceled, or lacks authority, the complete run is rolled back.
- Receipts retain node IDs, operation names, timings, bounded output summaries, errors,
  operation counts, and emitted-event counts.
- Stateful graph instances support begin-play and named events, deterministic fixed-step
  ticking, pause/resume, bounded catch-up, excess-time reporting, and validated hot swaps.
- Hot swaps preserve runtime state only when schema, ABI, validation, and program identity
  remain compatible.

Operation definitions and runtime handlers reject accidental replacement by default.
Plug-ins must explicitly request replacement, and both registries are safe for concurrent
lookup and registration.

This reference behavior supplies golden tests for the C++ implementation. Native parity
requires identical state transitions and error classes for the same manifest and context;
wall-clock timings do not need to match.

## Near-Term Control Flow

The first reversible slice supports operation calls, literal values, ordered flow,
and data links. The next extensions should be added in this order:

1. Branch, switch, sequence, loop-with-budget, delay, timer, and async task nodes.
2. Events, reusable functions, local variables, structs, enums, and components.
3. State machines with transition rules and visual runtime state.
4. Authority, replication, prediction, rollback, and deterministic event metadata.
5. Breakpoints, value watches, frame captures, per-node timing, and replay debugging.
6. C++ and Rust binding generation from the same operation registry.

Arbitrary unbounded loops are not accepted in a shipping graph. Users receive a
clear explanation and safe alternatives such as bounded iteration, scheduled work,
or an explicitly profiled native operation.

## Native Editor Workflow

The code editor treats C++ as a first-class project language. It discovers the
nearest CMake project, keeps separate incremental Debug, Release, and
RelWithDebInfo build trees, and streams configure/build/test output from a worker
thread so the Qt heartbeat remains responsive. Build, build-and-test, rebuild,
clean, and current-file static analysis share one build-session contract.

On Windows, the service discovers Visual Studio with `vswhere` or its installed
layout and initializes `VsDevCmd.bat` itself. Users do not need to launch TC from
a Developer Command Prompt. This exposes MSVC, MSBuild, Ninja, LLVM formatting,
Clang analysis, and LLDB when those Visual Studio components are installed.

MSVC, GCC/Clang, and Python traceback locations are structured diagnostics.
Clicking either a Problems row or a diagnostic line in the output log opens the
source file at the reported line and column. C++ formatting uses the nearest
`.clang-format`; Python formatting continues to use the Python quality service.

The next native-editor qualification gates are CMake Preset selection, executable
target discovery, launch profiles, breakpoints and watches, sanitizer presets,
CPU/memory profiling, remote targets, and source-mapped gameplay graph debugging.
These are explicit remaining gates, not capabilities inferred from successful
compilation.

## DCC Capability Evidence

`dcc_capability_audit_service` reports only structurally executable operation
registries and concrete rigging-adapter handlers. It deliberately does not treat
an interchange-format declaration as proof that a host tool works.

- TC-native currently implements all 34 shared rigging operation handlers.
- Maya has the full translated rigging contract and a concrete host module.
- MotionBuilder has a partial translated rigging contract.
- Blender, Houdini, Substance Painter, Unreal, and Unity expose registered bridge
  operations, but each still needs live-host release qualification.
- 3ds Max currently has no authoritative operation registry or rigging adapter.

Behavioral parity, save/readback correctness, animation fidelity, and live-host
performance remain separate test requirements from structural callability.
