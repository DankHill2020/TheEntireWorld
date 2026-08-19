# Tech Connector cleanup and consolidation pass

Date: 2026-08-08

## Scope and safety rules

This pass covered the complete `tech_connector` package, its release-tier staging rules,
the native runtime validation lane, and generated package outputs at the tools root.
Existing feature work, compatibility import paths, local settings, qualification receipts,
change history, the active knowledge index, and the modified project-analysis database were
preserved unless an artifact was independently reproducible or proven redundant.

## Removed artifacts

Roughly 51.9 GB of reproducible local output was removed across old release stages, frozen
distributions, test caches, native build trees, Python bytecode, and these verified hotspots:

- `tech_connector/.ai_studio/unreal_request_log.jsonl` (9,853,005,611 bytes): an unbounded
  request log. The writer is now bounded before the file was removed.
- `tech_connector/knowledge/index/legacy` (1,878,536,192 bytes): an ignored legacy index
  with no runtime references. The active `knowledge_index_v2.sqlite` remains.
- `tech_connector/data/capability_registry.json` (139,674,223 bytes) and the tracked shard
  set (about 105 MB): generated inventories of a developer virtual environment and retired
  local roots. Portable built-in DCC capabilities now come from source definitions; runtime
  scans remain user/project data rather than public source artifacts.
- `tech_connector/game_engine/native/.tech_connector` (13,745,506 bytes): an ignored,
  reproducible in-source native build cache.
- Empty SQLite WAL remnants and the empty `services/tests` directory.

The following tracked dead files were removed and remain recoverable through Git history:

- `editor/completion.py`
- `ui/editor_panel.py`
- `ui/tabs.py`
- `ui/routing_metrics_dashboard.py`
- `knowledge/mcp_unreal_maya_knowledge_config.json.bak`, which was byte-identical to the
  canonical configuration and had no references.

## Consolidation and recurrence prevention

- Added one shared bounded-JSONL implementation for Unreal bridge requests, backend and UI
  diagnostics, route metrics, Unreal development evaluations, verified feature recipes, and
  technique episodes.
- Unreal request logs rotate at 16 MiB with three archives. General diagnostics rotate at
  8 MiB with two archives. Feature recipes and technique episodes use 16 MiB and three archives.
- Removed the obsolete duplicate package docstring from `services/dcc/__init__.py` while
  retaining the compatibility aliases themselves.
- Release tiers now exclude runtime state, caches, backups, bytecode, WAL files, project
  analysis databases, legacy indexes, in-source native builds, and Unreal plugin `.build`
  output. This prevents the observed multi-gigabyte generated trees from entering releases.
- Native-only Python tests now skip with a clear build-lane instruction when the generated
  DLL is absent. A clean source checkout no longer fails merely because a build cache was
  correctly removed.
- Capability registry loading now detects either a monolithic file or its sibling shard
  directory, validates shard paths against directory traversal, and always provides the ten
  portable built-in DCC bridge capabilities.
- Developer-specific roaming-profile fallbacks were removed from GIMP and Photoshop bridge
  setup. Installers now honor `APPDATA` or the current user's home directory.

## Structural decomposition

All ten maintained Python modules that exceeded 4,000 lines were split behind their existing
public import paths:

- editor assistance, image canvas/editor orchestration, chat capability routing, and workflow
  authoring were separated into focused services or cooperative mixins;
- prompt routing rules and goal-gap capability rules were separated from their orchestration
  entry points;
- the project-edit agent is a compatibility facade over six dependency-ordered modules;
- implementation-plan quality is a compatibility facade over five dependency-ordered modules
  and a dedicated declaration-contract validator;
- the 3D mesh painter is a 235-line facade over worker, geometry, support, and six viewport
  mixin modules;
- project-edit workflow helpers were separated into nine modules; the former 17,350-line
  orchestration runner is now a 181-line compatibility facade over explicit planning,
  contract, requirement, generation, verification, retry-attempt, and completion phases.
  Cross-phase returns and retry-loop continues use private control-flow signals derived from
  `BaseException`, so ordinary workflow error handlers cannot swallow them. Shared imports
  live in one dependency module rather than being copied across every phase.

New and materially refactored APIs use the project docstring convention with a summary,
`:param` entries, and `:return:` where applicable.

## Package ownership consolidation

Viewer and editor implementations are now organized by product surface instead of being
mixed into the root `ui` directory:

- `ui/dcc_viewer` owns connected-host driving, scene documents, component picking, the GPU
  viewport, and performance evidence;
- `ui/dcc_viewer/mesh_painter` owns the complete decomposed 3D painter implementation and
  its PBR texture service;
- `ui/game_engine` owns animation, sequencing, simulation, physics-joint, and Unreal editor
  surfaces while headless systems remain in `game_engine`;
- `ui/image_viewer` owns brush shapes, the image canvas/editor, and visual-art inspection;
- the viewer command implementation and engine console now live in `game_engine/integration`
  and `game_engine/runtime`, respectively.

Twenty-nine legacy module paths remain as small module-identity aliases. This preserves
external DCC scripts, singleton state, and monkeypatch behavior without keeping duplicate
implementations. New internal imports use only canonical package paths. The ownership tree
and dependency direction are documented in `docs/PACKAGE_ARCHITECTURE.md`, `ui/README.md`,
and `game_engine/README.md`.

## Deliberately retained

- `knowledge/index/knowledge_index_v2.sqlite` (about 1.73 GB): runtime knowledge search has
  explicit references to it. Reducing installer size requires a separate index distribution,
  compression, or first-run acquisition design.
- `project_analysis/project_analysis.db`: tracked and actively modified user/project data.
  Moving mutable analysis state outside the source tree requires a migration plan.
- `.ai_studio` settings, receipts, intelligence data, and change history: local user state,
  not dead source. Release staging excludes the entire directory.
- `services/dcc` aliases and other root compatibility shims: public plugin/script import
  surfaces. Static zero-inbound-import results are insufficient grounds for deletion.
- Exact copies in `cpp_bridges` and `examples/cpp_bridges`, icon aliases, and three named
  Unreal snippet files: these have example, dynamic-name, or compatibility value and were not
  deleted without stronger ownership evidence.

## Validation evidence

- Static Python inventory: 977 modules, zero parse errors, zero empty non-package modules.
- Focused cleanup/release/logging tests: 9 passed.
- CPython 3.14.6 core suite with a clean native build: 367 passed, 2 skipped.
- Clean-source core suite after deleting the native build cache: 360 passed, 9 explicitly
  skipped native-only tests.
- Maintained post-consolidation suite: 377 passed, 9 skipped, including focused tests
  for phase order, cross-phase returns, retry-loop continuation, and the public early-return
  contract, plus package ownership, compatibility identity, relocated QML resolution, camera
  fanout, active-viewer command ownership, and asynchronous effect baking.
- Compatibility import audit: all 29 legacy viewer/editor paths resolve to the same module
  objects as their canonical implementations.
- Selected legacy viewer lane: 39 passed, zero failed. Seventeen viewport helpers that had
  been accidentally nested during the earlier large-file decomposition are restored as class
  methods, constructed embedded viewers immediately own local commands, and DCC camera
  workers expose an injectable bridge boundary for deterministic concurrency tests.
- Focused routing/goal-gap regression: 21 passed and 17 subtests passed.
- Focused mesh-painter behavior regression: 14 passed.
- Full `tech_connector` Python 3.14 compile sweep: zero syntax errors.
- Maintained Python size scan: zero files above 4,000 lines; the largest is 3,915 lines.
- Tracked-source profile/key-marker scan: no developer-profile absolute paths and no PEM
  private-key markers.
- Native MSVC Release build: successful; CTest 3/3 passed.
- Full-tools staging: 1,870,454,081 bytes, 1,439 files, and zero forbidden generated-state
  matches. The retained active knowledge index accounts for 1,732,894,720 bytes.
- Examples/legacy suite baseline: 1,169 passed, 166 subtests passed, 104 failed. Failures span
  older routing, project-edit, Unreal capability, and viewer integration contracts; they are
  not caused by the cleanup/log-retention paths and remain a separate compatibility backlog.

## Remaining maintenance backlog

- Decide how to ship or acquire the 1.73 GB knowledge index without making every source-tier
  package carry it uncompressed.
- Migrate mutable project-analysis data out of the tracked source directory, with an explicit
  upgrade path for existing databases.
- Triage the 104 examples/legacy failures by ownership and either update maintained contracts,
  move historical tests to a declared legacy lane, or retire them with migration notes.
- Address native C++23 warning noise from Eigen 3.4 and the bundled tinyexpr C source so new
  project warnings remain visible.
