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

`project_roots` is optional, but passing the tagged file/package/workspace scope
keeps experimentation responsive and matches how the UI should narrow work when
the user tags a specific source.

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
