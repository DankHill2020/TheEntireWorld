# Tech Connector Headless API

Tech Connector can be used without the Qt desktop UI through the official
headless Python API:

For a concept-first explanation of API version 2 reasoning, contextual threads,
progress events, runtime tools, modular feature discovery, extensions, and
complete examples, read
[REASONING_RUNTIME_API.md](REASONING_RUNTIME_API.md).

```python
from tech_connector.api import TechConnectorHeadlessAPI

api = TechConnectorHeadlessAPI(
    project_root="C:/project",
)

status = api.verify_license()
graph = api.plan_prompt("Create a Maya-to-Unreal export pipeline")
dry_run = api.execute_action_graph(graph, dry_run=True)
```

The same process can run with or without the desktop UI. The UI is the visual
front end for review, confirmation, node editing, and status. The headless API
uses the same planner, action graph, DCC bridge, execution, repair, and
provenance stack for scripts, CI, local services, or another application.

Process-wide LLM queue telemetry and targeted cancellation are also available
through `api.llm_queue_status()` and `api.cancel_llm_request(request_id)`. See
[LLM_QUEUE_MANAGEMENT.md](LLM_QUEUE_MANAGEMENT.md) for scheduling categories,
configuration, deadlines, superseding, and cancellation semantics.

## Simple AI API

For direct generation, use the provider-neutral `api.ai` namespace. It keeps
credentials out of results and makes routing inspectable before a paid call:

```python
from tech_connector.api import create_api

api = create_api(project_root="C:/project")

catalog = api.ai.models()
local = api.ai.local_recommendation()
route = api.ai.route(depth="deep")
result = api.ai.generate(
    "Explain the safest way to refactor this Maya exporter.",
    system="Be concise and cite affected symbols.",
    depth="deep",
)

if not result.ok:
    raise RuntimeError(result.error)
print(result.result["text"])
print(result.result["route"])
```

`local_recommendation()` reports the detected GPU, target models, currently
active installed fallbacks, missing recommended downloads, and runtime guidance.
Use `api.ai.benchmark_local()` for a short Ollama speed probe; it reports load
time and generated tokens per second and does not contact a cloud provider.

Depths are `fast`, `balanced`, `deep`, and `maximum`. With OpenAI automatic
selection enabled they map to GPT-6 Luna, GPT-6.1 Sol, GPT-6.1 Sol with higher
reasoning, and GPT-6 Astra respectively. An explicit unrelated model is
preserved. Cloud failure never silently changes the model during a run;
`allow_local_fallback=True` must be set explicitly.

Use `api.reasoning` when you need project context, planning, tools, progress
events, or the full Tech Connector orchestration pipeline.

## Discovering operations and handling errors

The API is self-describing, so integrations do not need to hard-code every
feature or signature:

```python
overview = api.describe()
matches = api.features.search("material generation")
help_payload = api.features.describe("ai.generate", "generate")

for parameter in help_payload["operations"][0]["parameters"]:
    print(parameter["name"], parameter["required"], parameter["default"])
```

Every `APIResult` keeps the existing `ok`, `result`, and `error` fields and now
also includes `error_detail` with a stable code, retry guidance, and a suggested
next action. Small scripts can use `unwrap()`:

```python
try:
    text = api.ai.generate("Summarize this scene").unwrap()["text"]
except TechConnectorAPIError as exc:
    print(exc.code, exc.retryable, exc.suggestion)
```

### Complete public surface inventory

Use `api.surface()` when building wrappers, bindings, or documentation. It
returns every supported core and namespace operation with its current Python
signature and documentation. Dynamic catalogs are identified separately so a
caller can enumerate them from their authoritative runtime source:

```python
surface = api.surface()

for operation in surface["operations"]:
    print(operation["path"], operation["signature"])

# Dynamic surfaces
dcc_functions = api.dcc.catalog()
editor_operations = api.kingdom.editor_capabilities().unwrap()
engine_coverage = api.kingdom.capability_report().unwrap()["value"]
runtime_tools = api.reasoning.tools().unwrap()
ui_actions = api.ui.catalog().unwrap()  # requires an attached UI for actions
```

`api.features.get("api.surface")` and
`api.features.invoke("api.surface", "list")` expose the same inventory through
the modular feature registry. The checked-in
[API_FUNCTION_CATALOG.md](API_FUNCTION_CATALOG.md) is generated from the current
DCC packages and documents every public module-level host function, including
functions without a friendly alias.

### Engine asset reimport and Level mesh binding

The editor Python API can keep a source-linked imported mesh and bind it to a
uniquely named Level actor. Reimport preserves the asset ID and advances its
revision; the next cook/package uses the updated source:

```python
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI

editor = TCEditorAPI("C:/project")
mesh = editor.import_asset("C:/source/Character.obj", type_id="tc.static_mesh")
editor.set_level_actor_render_mesh(level_asset_id, "Player", mesh.asset_id)

# After editing C:/source/Character.obj:
editor.reimport_asset(mesh.asset_id)
```

The current native graphical player imports OBJ render meshes. This binding is
not a full skeletal DCC reimport workflow; preserve vertex topology when using
an existing skin binding, and verify the packaged character before release.

## Connected Services and Smart Functions

`api.integrations` is the official boundary for Slack, Discord, Jira,
Confluence, ClickUp, connected-account state, and chat smart references such as
`@Slack.pipeline-alerts` and `@Maya.scene.select`.

```python
status = api.integrations.status("slack").unwrap()["value"]
applications = api.integrations.applications().unwrap()["value"]

suggestions = api.integrations.suggest("Slack.pipe").unwrap()["value"]
context = api.integrations.resolve(
    "Send the validation report to @Slack.pipeline-alerts"
).unwrap()["value"]
```

Status results never return raw credentials. Secret fields are either empty or
masked by the connected-account service.

Cached channel/user discovery is side-effect free. Set `refresh=True` only when
the caller wants a live provider request:

```python
cached = api.integrations.targets("slack").unwrap()["value"]
live = api.integrations.targets("slack", refresh=True).unwrap()["value"]
setup = api.integrations.oauth_url("slack").unwrap()["value"]
```

Dispatch is fail-closed. Previewing requires no mutation approval; execution
requires `approved=True` and preserves explicit targets rather than silently
falling back to a different Slack or Discord destination:

```python
preview = api.integrations.dispatch(
    "@Slack.pipeline-alerts Build completed successfully",
    dry_run=True,
)

sent = api.integrations.dispatch(
    "@Slack.pipeline-alerts Build completed successfully",
    approved=True,
)
```

The same operations are discoverable as feature
`integrations.connected_services`. Small scripts may import
`integration_status`, `integration_suggestions`, and `dispatch_integration`
directly from `tech_connector.api`.

## Namespace Coverage

The supported high-level namespaces are:

| Namespace | Purpose | Dynamic discovery |
| --- | --- | --- |
| `api.ai` | Model catalog, routing, local recommendations, benchmarks, generation | `api.ai.models()` |
| `api.reasoning` / `api.runtime` | Context preparation, reasoning, chains, tools | `api.reasoning.capabilities()`, `api.reasoning.tools()` |
| `api.features` | Feature search, signatures, manifests, generic invocation | `api.features.manifest()` |
| `api.integrations` | Connected services, smart references, targets, approved dispatch | `api.integrations.applications()` |
| `api.dcc` | Host function aliases and bridge execution | `api.dcc.catalog()` |
| `api.kingdom` / `api.game_engine` | Game-engine runtime and project editor | `api.kingdom.editor_capabilities()` |
| `api.garden` / `api.scene_viewer` | Active scene-viewer commands | `api.garden.commands()` |
| `api.ophanim` / `api.image_editor` | Viewport capture and image editing | `api.describe()` |
| `api.ui` | Actions on an explicitly attached desktop window | `api.ui.catalog()` |

Call `api.describe()` for the stable namespace map and `api.surface()` for the
exact operation list used by the installed version.

The Kingdom namespace also exposes the full project editor contract without
requiring callers to import internal engine modules:

```python
operations = api.kingdom.editor_capabilities().unwrap()
coverage = api.kingdom.capability_report().unwrap()["value"]
help_payload = api.kingdom.editor_describe("asset_dependency_graph").unwrap()
graph = api.kingdom.editor_call(
    "asset_dependency_graph",
    asset_id="tc.asset.example",
).unwrap()["value"]
```

`capability_report()` lists all registered asset types by family and maturity,
plus the declared editor operation groups and any missing callable handlers.
`runtime_ready` describes a usable runtime path; only `production_ready` claims
production qualification. Registry entries, editor pages, and API methods alone
do not establish Unreal or Unity parity. See the
[engine parity program](ENGINE_PARITY_PROGRAM.md) for the required workflows and
evidence gates.

The first UI authoring tranche is available through the same project editor
surface. It creates and validates a widget hierarchy, evaluates anchor-based
layouts at chosen viewport sizes, and stores a layout preview cook artifact:

```python
created = api.kingdom.editor_call("create_ui_document", name="MainMenu").unwrap()["value"]
asset_id = created["asset_id"]
preview = api.kingdom.editor_call(
    "preview_ui_document", asset_id=asset_id, viewport=(390, 844)
).unwrap()["value"]
```

`update_ui_document`, `validate_ui_document`, and `cook_ui_document` are also
declared editor operations. A Level can bind the validated document's properties
as `runtime_world.ui_document`; the Windows/D3D11 package compiler then embeds
panel, text, button, and packaged-texture image records for the native player.
An image widget must reference a registered `tc.texture` asset and the scene's
`runtime_world.assets` must declare that texture's ID, source, and hash. Missing
packaged textures fail compilation. A button with `on_activate: "save_game"`
invokes the packaged save path. The player now reflows authored anchors and
parent layout at window resize; legacy packages retain their scaled layout.
The acceptance project checks real D3D11 captures at two window sizes. A UI
Document may set `canvas.safe_area` to `[left, top, right, bottom]` pixel
insets; preview and packaged runtime root anchors use the inset rectangle,
including mouse hit-testing. Widgets may also set `min_viewport_width` in
pixels; narrower viewports hide that widget and its descendants from drawing,
mouse activation, and keyboard/gamepad focus. The acceptance project checks
inset and narrow D3D11 captures plus Save button activation. This is still a
limited runtime slice:
platform accessibility, localization, DPI and narrow-device layout matrices,
console-safe-area policies, and cross-platform player UI are not yet qualified,
so the asset remains
`authoring_preview`.

### Player target selection

The explicit target API prevents a Windows package from being mistaken for a
console release:

```python
from tech_connector.game_engine.runtime.tc_player_build_service import (
    build_player_for_target, runtime_platform_capabilities,
)

targets = runtime_platform_capabilities()["targets"]
pc_build = build_player_for_target(scene_path, output_dir, target="windows_pc")
```

`windows_pc` builds the current D3D11/XInput player. `xbox_series_xs` and `ps5`
are visible in the capabilities report but deliberately reject package builds
until native platform implementations and device acceptance exist. The shared
gamepad actions use south/east/west face-button positions; Xbox A/B/X and
PlayStation Cross/Circle/Square are mapped to those positions by platform input
adapters. Today, only the Windows XInput adapter is implemented. Xbox requires
a GDKX console project and Xbox renderer/platform services; PS5 requires
PlayStation partner SDK access and a native renderer/platform layer. Neither
console has a shippable binary, certification result, or hardware acceptance
receipt yet.

Gameplay and UI buttons can be configured in a Level's `runtime_world` before
compilation:

```python
runtime_world["gamepad_bindings"] = {
    "jump": "NORTH", "crouch": "LEFT_SHOULDER", "crawl": "RIGHT_SHOULDER",
    "ui_confirm": "WEST", "ui_cancel": "EAST", "ui_menu": "MENU",
}
```

Supported button names are `SOUTH`, `EAST`, `WEST`, `NORTH`, `LEFT_SHOULDER`,
`RIGHT_SHOULDER`, and `MENU`. Defaults are south/east/west for
jump/crouch/crawl, and south/east/menu for UI confirm/cancel/menu. The compiler
rejects unknown names and duplicate bindings within gameplay or UI context.
In the Windows player, UI buttons with `on_activate` values `rebind_jump`,
`rebind_crouch`, and `rebind_crawl` prompt for the next gamepad face or shoulder
button and update the corresponding gameplay action; an
occupied gameplay button or Menu is rejected without changing the mapping.
The Windows player persists successful rebinds to a versioned, checksummed,
atomically replaced per-scene profile under `%LOCALAPPDATA%/TechConnector/TCPlayer/profiles`.
`--input-profile <path>` overrides that location, including for acceptance runs.
Malformed or checksum-invalid profiles are rejected and authored bindings stay
in force. A failed profile write also rejects the proposed rebind, leaving the
current mapping and button label unchanged. The acceptance harness verifies
save/load across two processes for Jump, Crouch, and Crawl, corrupt-load
rejection, and failed-write rollback with simulated input only. The authored
third-person HUD includes Save and Load buttons. A simulated Xbox Menu → D-pad
→ Confirm route checks that Load receives focus, is visibly highlighted, and
restores the saved slot across player processes. Save/Load actions and F5/F6
now show a temporary HUD result (`Saved`, `Loaded`, `Save failed`, or
`Load failed`); the missing-save path is exercised and captured separately.
A complete settings screen and
physical Xbox/PS5 controller qualification remain open.
When Windows gamepad input is lost, controller-owned UI focus and a pending
rebind are cleared so keyboard controls can resume. The packaged simulated
disconnect check opens UI focus, drops input, then records movement from the
keyboard. It also simulates reconnection and verifies the controller can
reopen UI focus. On reconnect, already-held buttons and a deflected stick are
ignored until released/neutral; fresh movement works before a deliberate Menu
press refocuses the HUD. This does not prove physical hot-plug behavior.
A second route starts a Jump rebind before input loss, then verifies that the
pending capture is cancelled, the original Jump label returns, keyboard
movement works, and reconnecting input can navigate the HUD again.
When XInput ownership moves directly from one connected controller slot to
another, the Windows player clears controller-owned focus and pending capture.
It treats buttons already held on the new controller as held, not fresh presses;
the new owner must release and press Menu again to focus the HUD. A packaged
scripted slot-switch check verifies the owner-change signal, keyboard fallback,
and visibly refocused Save button. Gameplay buttons and a deflected movement
stick present at handoff are also ignored until each returns to neutral; a
later deliberate stick input is accepted. This is simulated input, not physical
multi-controller hot-plug qualification.
The soak verifier accepts `--min-draw-calls` and `--require-motion-search`
for an explicitly scoped imported-character package; the default remains the
260-draw synthetic stress check. Timing and memory receipts must be interpreted
within their named scene, hardware, renderer, and scripted route.
`--require-mixed-motion` additionally checks each complete 240-frame route
cycle for strafing, crouch, crawl, jump, and idle, plus bounded character
position. The player provides `--scripted-motion-soak` to generate that route
after the 380-frame traversal.
The acceptance project also captures a 480×270 outer window (464×231 client)
and clicks the lowest Crawl control, proving that the compact two-column
controls remain reachable in this short Windows viewport. This is not a DPI
or device-scale matrix.

Save migration accepts v1 `POS` and v2 `BODY` records (plus `VAR`) only when records are
complete, finite, non-duplicated, and newline-terminated. Malformed legacy
primaries are rejected without changing the world; a valid `.bak` can still
restore the prior state. This does not cover future save-schema versions or a
full platform storage matrix.
New v3 saves include the source scene ID in a checksummed `SCENE` record. A
save bound to another scene is rejected before applying any world state, even
if entity names match. Older v3 files without `SCENE` remain readable for
migration; their scene origin cannot be authenticated retroactively. Backup
rotation also refuses to copy a valid but foreign-scene primary over this
scene's `.bak`, preserving the last compatible recovery point.

Windows audio telemetry now distinguishes a buffer accepted by XAudio2
(`submitted`) from a buffer-end callback (`completed`). Packaged acceptance
requires a matching completion for the authored cue. This does not establish
audible output quality, latency, or behavior across audio devices.
Source-voice volume setup now fails the cue immediately if XAudio2 rejects it,
rather than reporting a successfully submitted cue with an unusable voice.
The exploration HUD has an `Audio: On` / `Audio: Muted` button that adjusts the
Windows mastering voice volume. A short-window packaged test clicks it twice,
checks both states, and still requires the cue buffer completion receipt. The
mute preference is saved per scene under `%LOCALAPPDATA%/TechConnector/TCPlayer/profiles`
as a versioned, checksummed `.tcaudio` file. `--audio-profile <path>` isolates
acceptance runs. Corrupt preferences fall back to Audio On, and a failed write
rolls the live mute state back. The desired mute state is retained if XAudio2
has no output device at launch and applied when a mastering voice can be
created later. The player opens XAudio2 lazily on the first cue, so a transient
startup device outage is not treated as a failed launch; a failed cue is still
reported as a failed `audio_event`. The audio-device matrix remains open.

Windowed PC saves now use `%LOCALAPPDATA%/TechConnector/TCPlayer/saves/<scene-key>`
instead of writing into installed `Content`. F5 saves and F6 loads the active
slot; authored `save_game` and `load_game` UI actions use the same path.
`--save-dir <path>` isolates a run or lets a distributor choose a stable
location. New packages derive the key from the source scene's persistent ID,
so moving an installation does not change it. On F6, a missing new-format save
can be migrated from the previous path-keyed directory or legacy installed
`Content`; existing legacy files are preserved. Older manifests without a
scene ID retain path-keyed behavior. Headless `--verify-save-roundtrip` still
writes its explicit fixture path.
See Microsoft's [GDK/GDKX overview](https://learn.microsoft.com/en-us/gaming/gdk/_content/gc/intro/overviews/introduction)
and Sony's [PlayStation partner onboarding](https://sonyinteractive.com/en/news/blog/showing-your-game-to-playstation/)
for the platform access paths.

## Reasoning Runtime API

API version 2 exposes the same shared reasoning runtime used by Tech Connector's
request engine:

```python
events = []
result = api.reasoning.run(
    "Find the rig export implementation and explain its dependencies",
    context={
        "active_tab": "Editor",
        "current_file_path": "C:/project/tools/exporter.py",
        "open_file_paths": ["C:/project/tools/exporter.py"],
        "selection_text": "def export_fbx(...): ...",
        "thread": [
            {"role": "user", "content": "We are improving the rig exporter."},
            {"role": "assistant", "content": "The Maya export path is the current focus."},
        ],
    },
    progress_callback=events.append,
)

print(result.result["response"]["action"])
print(result.result["runtime"]["model_route"])
```

The `thread` or `messages` collection is canonical request context. It is
independent of any UI render limit and is sanitized before entering the runtime.
Credential-like keys such as API keys, passwords, cookies, and tokens are
removed from context automatically.

Runtime discovery and preparation are available separately:

```python
features = api.reasoning.capabilities()
snapshot = api.reasoning.snapshot("Inspect the current project")
prepared = api.reasoning.prepare(
    "Explain this function",
    context={"current_file_path": "C:/project/tool.py"},
)
tools = api.reasoning.tools()
```

`api.runtime` is an alias for `api.reasoning`. Module-level helpers are also
available:

```python
from tech_connector.api import (
    prepare_reasoning_request,
    reason,
    reasoning_capabilities,
    reasoning_snapshot,
)

result = reason("Find function create_rig_mapping()", settings=settings)
```

Registered runtime tools preserve their mutability and risk contracts. Read-only
tools may execute directly. Mutating tools require explicit approval:

```python
preview = api.reasoning.execute_tool(
    "dcc.execute",
    {"host": "maya", "operation": "create_locator"},
    dry_run=True,
)

executed = api.reasoning.execute_tool(
    "dcc.execute",
    {"host": "maya", "operation": "create_locator"},
    approved=True,
)
```

Every reasoning response is an `APIResult`. Its `result` includes the stable
schema, serialized response, integer progress events, activity events, and the
reasoning-runtime snapshot. No Qt objects or UI modules are required.

### Modular Feature Registry

Capabilities are registered at feature and runtime-adapter granularity rather
than maintained as one hardcoded list:

```python
manifest = api.features.manifest()
context_features = api.features.list(category="runtime.context")
index_features = api.features.list(category="runtime.index")

tech_context = api.features.invoke(
    "runtime.context.tech_connector_context",
    "active_context",
)
```

Each descriptor includes:

- `feature_id`
- `category`
- `version`
- `description`
- `operations`
- `dependencies`
- `permissions`
- `available`
- `source`
- per-operation schemas and metadata

Installed reasoning-runtime adapters are discovered from the actual kernel.
Context, reasoning, capability, validation, code-policy, and rule adapters
register their directly invokable operations. Code-understanding, knowledge,
index, symbol-lookup, and escalation adapters are exposed as independently
discoverable modules and identify the higher-level runtime operation that owns
their typed execution.

External packages can register features without modifying Tech Connector:

```python
from tech_connector.services.api_feature_registry_service import APIFeatureDescriptor

api.features.register(
    APIFeatureDescriptor(
        feature_id="studio.asset_review",
        category="studio",
        version="1.0",
        description="Review an asset against studio rules.",
        operations=("review",),
        source="studio_tools.asset_review",
    ),
    {"review": review_asset},
)
```

Only operations declared by the descriptor can be invoked. Registration rejects
undeclared handlers and duplicate feature IDs unless replacement is explicitly
requested.

## Running Prompt Chains

Prompt chains let callers run an entire multi-step process from natural
language without manually stitching action graphs:

```python
chain = api.execute_prompt_chain(
    [
        "In Maya, select the top two rig roots and export the hierarchy to FBX",
        "In Unreal, import that FBX into /Game/Characters",
        "Find the imported asset and report the package path",
    ],
    approved=True,
)

for step in chain.result["steps"]:
    print(step["understanding"], step["execution"]["status"])
```

For preview/review flows, plan the chain without running it:

```python
planned = api.plan_prompt_chain(
    "Find the rig export function then build the Maya export action graph"
)
```

Each chain step includes the original prompt, what Tech Connector understood,
the generated action graph, execution status, and errors/results. Set
`dry_run=True` to validate the full chain without executing mutating actions.

## Prompt To Action Order

The UI and headless API use the same official sequence. Use these calls when
experimenting outside the desktop app:

```python
# 1. Create/load the same licensed API boundary the UI uses.
api = TechConnectorHeadlessAPI(
    project_root="C:/project",
)

# 2. Preview what the prompt means.
graph = api.plan_prompt(
    "Find function create_rig_mapping()",
    project_roots=["C:/depot/tools/maya_tools/Rigging"],
)

# 3. Preflight the graph without mutating files or DCC state.
dry_run = api.execute_action_graph(graph, dry_run=True)

# 4. Execute only after the caller/user approves mutating work.
report = api.execute_action_graph(graph, approved=True)
```

For multi-step processes, the equivalent UI flow is:

```python
# 1. Plan every prompt step and inspect understanding/graphs.
planned = api.plan_prompt_chain(
    [
        "Find function create_rig_mapping()",
        "Find function create_rig_from_mapping()",
    ],
    project_roots=["C:/depot/tools/maya_tools/Rigging"],
)
chain_prompts = [step["prompt"] for step in planned["steps"]]

# 2. Preflight the entire chain.
preview = api.execute_prompt_chain(
    chain_prompts,
    dry_run=True,
    project_roots=["C:/depot/tools/maya_tools/Rigging"],
)

# 3. Run the same chain after approval.
result = api.execute_prompt_chain(
    chain_prompts,
    approved=True,
    project_roots=["C:/depot/tools/maya_tools/Rigging"],
)
```

`project_roots` is optional. By default Tech Connector uses the primary project,
all secondary folders configured with **+ Add Folder**, and the installed tools
root. The tools root is permanent so built-in APIs remain discoverable even when
the user's project lives on another drive. Passing `project_roots` explicitly
narrows one request to the tagged file/package/workspace scope.

## Calling Functions

Plain Python function access should go through this API boundary:

```python
result = api.call_function(
    "my_tools.exporters.export_fbx",
    kwargs={"selection": ["root"], "path": "C:/tmp/out.fbx"},
    extra_roots=["C:/project"],
    stamp_project_provenance=True,
)

if result.ok:
    print(result.result["value"])
else:
    print(result.error)
```

## Calling DCC Functions

DCC-specific functions should be executed inside their host application instead
of imported in normal Python. Use the official host namespaces for common
operations:

```python
result = api.dcc.maya.create_rig_from_mapping(
    body_joint_map=body_joint_map,
    face_joint_map=face_joint_map,
)

print(result.result["output"])
```

Official aliases mean callers do not need to remember package paths for common
operations:

```python
rig = api.dcc.maya.create_rig(body_joint_map=body_map, face_joint_map=face_map)
mapping = api.dcc.maya.create_rig_mapping(root_joint="origin")
asset = api.dcc.unreal.find_assets("BP_Player", expected_class="Blueprint")
```

Every discovered public DCC function is documented in
[API_FUNCTION_CATALOG.md](API_FUNCTION_CATALOG.md) with its friendly call form,
resolved target function, signature, args/defaults, docstring summary, and
source location. Catalog entries also include related functions, known
prerequisites/consumers, and likely same-module helpers when that relationship
can be inferred from source or workflow rules.

The same aliases are also available under the callable `call_dcc_function`
namespace:

```python
asset = api.call_dcc_function.unreal.find_assets(
    "BP_Player",
    expected_class="Blueprint",
)
```

You can inspect the current alias map:

```python
aliases = api.dcc.aliases()
print(aliases["maya"]["create_rig"])
```

You can inspect the generated catalog in code:

```python
catalog = api.dcc.catalog()
maya_functions = catalog["hosts"]["maya"]
```

For custom or newly discovered functions, use the host namespace escape hatch:

```python
result = api.dcc.maya.call(
    "custom_tools.rig.cleanup",
    kwargs={"delete_unused": True},
)
```

The lower-level form is still available when the full package path is known:

```python
result = api.call_dcc_function(
    "unreal_tools.assets.find_asset_path_by_name",
    "BP_Player",
    host="unreal",
    kwargs={"expected_class": "Blueprint"},
)
```

The API verifies the current entitlement before execution. Personal,
commercial, and enterprise license tokens include `official_api_access`.
Offline community/source-view mode does not unlock programmable API access.

## Argument Reference

### `TechConnectorHeadlessAPI(...)`

- `settings`: Optional non-secret settings dictionary. If omitted, Tech
  Connector loads saved settings and the OS-protected entitlement cache.
- `project_root`: Optional project directory used for prompt planning,
  provenance markers, and Python import roots.
- `licensing_context`: Optional licensing adapter override for embedded hosts and
  tests. Production clients verify cached entitlements using the public keys in
  `config/licensing.json`; no shared verification secret belongs in a client.
- `commercial_use`: Declares whether the current operation is commercial so
  Community project-registration and accepted-terms rules can be evaluated.
- `app_major_version`: Optional host-version override for embedded tests. Normal
  clients use the current Tech Connector major version automatically.
- `require_entitlement`: Retained for source-development compatibility. Official
  execution remains entitled unless an explicit non-frozen contributor bypass
  is enabled; status and diagnostics remain available while locked.
- `command_router`: Optional router override, mainly for tests or embedded
  services. Normal callers can omit it.

### `api.call_function(entry_point, *args, kwargs=None, extra_roots=None, stamp_project_provenance=False)`

- `entry_point`: Full Python callable path, such as
  `"my_tools.exporters.export_fbx"` or `"my_tools.exporters:export_fbx"`.
- `*args`: Positional arguments passed to the callable.
- `kwargs`: Keyword arguments passed to the callable.
- `extra_roots`: Extra directories added to `sys.path` before importing the
  callable.
- `stamp_project_provenance`: When `True`, writes a transparent
  `.tech_connector/provenance.json` record in `project_root`.

Use this for normal Python functions that can import and run in the current
Python process.

### `api.dcc.<host>.<alias>(*args, **kwargs)`

- `host`: One of the official host namespaces, such as `maya`, `unreal`,
  `blender`, `motionbuilder`, `substance_painter`, `houdini`, or `unity`.
- `alias`: Friendly official API name, such as `create_rig`, `create_rig_mapping`,
  or `find_assets`.
- `*args`: Positional arguments passed through the host bridge to the resolved
  DCC function.
- `**kwargs`: Keyword arguments passed through the host bridge to the resolved
  DCC function.

Use this for the cleanest official API calls. The alias resolves to a canonical
package function and still executes through the same DCC bridge stack.

### `api.dcc.<host>.call(name, *args, kwargs=None, stamp_project_provenance=True)`

- `name`: Either an official alias or a full function path. Full paths are used
  directly, for example `"custom_tools.rig.cleanup"`.
- `*args`: Positional arguments for the DCC function.
- `kwargs`: Keyword arguments for the DCC function.
- `stamp_project_provenance`: Writes a provenance marker by default.

Use this when a function has no friendly alias yet.

### `api.call_dcc_function(entry_point, *args, host="", kwargs=None, stamp_project_provenance=True)`

- `entry_point`: Full DCC function path, such as
  `"maya_tools.Rigging.create_rig.create_rig_from_mapping"`.
- `*args`: Positional arguments passed through the DCC bridge.
- `host`: Optional explicit host. If omitted, Tech Connector tries to infer the
  host from known package domains.
- `kwargs`: Keyword arguments passed through the DCC bridge.
- `stamp_project_provenance`: Writes a provenance marker by default.

Use this lower-level form when you already know the package path.

### `api.plan_prompt(prompt, project_roots=None)`

- `prompt`: Natural-language request to turn into a deterministic action graph.
- `project_roots`: Optional list of directories to search for functions,
  workflows, and dependencies. Defaults to the API project root and Tech
  Connector tools root.

Returns an action graph dictionary.

### `api.plan_prompt_chain(prompts, project_roots=None)`

- `prompts`: Either a list/tuple of prompt steps or a simple text chain split by
  lines, arrows, or the word `then`.
- `project_roots`: Optional list of directories to search for functions,
  workflows, and dependencies.

Returns a prompt-chain dictionary where each step includes the prompt,
understanding, intent, confidence, and generated action graph.

### `api.execute_prompt_chain(prompts, approved=False, dry_run=False, stop_on_error=True, policy=None, project_roots=None)`

- `prompts`: Prompt steps to plan and execute in order.
- `approved`: Set `True` only when the caller has approval to run mutating
  actions.
- `dry_run`: Set `True` to preflight every planned step without executing.
- `stop_on_error`: When `True`, later steps are skipped after the first failed
  execution report.
- `policy`: Optional execution policy overrides applied to each step.
- `project_roots`: Optional planning/search roots.

Returns `APIResult` with per-step prompt understanding, action graph, execution
report, and stop reason when the chain fails.

### `api.execute_action_graph(graph, approved=False, dry_run=False, policy=None)`

- `graph`: Action graph returned by `plan_prompt` or created by another
  official planner.
- `approved`: Set `True` only when the caller has approval to run mutating
  actions.
- `dry_run`: Set `True` to validate/preflight without executing actions.
- `policy`: Optional execution policy overrides. Tech Connector automatically
  adds `official_api`, `license_tier`, and prompt/project metadata.

Returns an execution report dictionary.

### `api.generate_pipeline_from_prompt(prompt, name="headless_pipeline", stamp_provenance=True)`

- `prompt`: Request to resolve into a pipeline graph and generated Python.
- `name`: Function name base for generated pipeline code.
- `stamp_provenance`: When `True`, inserts a Tech Connector provenance header in
  generated code.

Returns `APIResult` with `result["code"]`, `result["graph"]`, and
`result["workflow_plan"]` when successful.

### `api.integrations.status(account_id="")`

- `account_id`: Optional connected-account ID such as `slack`, `discord`,
  `atlassian`, `github`, or `perforce`. Empty returns every account.

Returns a sanitized `APIResult`; configured secrets are masked.

### `api.integrations.suggest(query="", active_hosts=(), limit=20)`

- `query`: Text after the chat `@`, for example `Slack.pipe`, `Maya.scene`, or
  `Jira.ART.b`.
- `active_hosts`: Optional live DCC host identifiers used to prioritize roots.
- `limit`: Maximum suggestions, clamped to 1–100.

### `api.integrations.resolve(text)`

Returns deterministic context for smart references, including connection
readiness and unresolved-target warnings.

### `api.integrations.targets(provider, refresh=False)`

- `provider`: `slack` or `discord`.
- `refresh`: When `False`, returns cached channels/users. When `True`, performs
  live provider discovery and updates only this API instance's in-memory cache.

### `api.integrations.oauth_url(provider, client_id="", redirect_uri="")`

Returns the provider's official setup or OAuth authorization URL. Supported
providers are Slack, Discord, Atlassian/Jira/Confluence, and ClickUp.

### `api.integrations.dispatch(text, default_title="Tech Connector Output", approved=False, dry_run=False)`

- `text`: Inline integration command containing one or more supported `@`
  references.
- `default_title`: Title applied to generated messages, issues, or pages.
- `approved`: Required for external writes.
- `dry_run`: Parses and returns references without contacting an external
  service.

Explicit Slack and Discord targets fail rather than using an unrelated default
webhook.

### `api.surface()`

Returns the complete supported operation inventory, per-namespace counts,
signatures, documentation, and links to dynamic discovery surfaces.

### `APIResult`

- `ok`: `True` when the call succeeded.
- `result`: Call-specific return payload.
- `error`: Error text when `ok` is `False`.
- `entitlement`: Verified license/tier metadata used for the call.
- `provenance`: Transparent usage marker generated for the call.

## Provenance

API calls can stamp transparent project provenance in:

```text
.tech_connector/provenance.json
```

The provenance record includes license tier, hashed account/license identifiers,
operation name, no-resale flags, no-AI-training flags, and official-API-required
flags. It does not include raw emails, secrets, or private tokens.

## Policy

This is the authorized path for programmatic function calls. Copying,
extracting, wrapping, reimplementing, training on, or building competing systems
from Tech Connector source, docs, prompts, traces, signatures, or call plans is
not permitted by the license.
