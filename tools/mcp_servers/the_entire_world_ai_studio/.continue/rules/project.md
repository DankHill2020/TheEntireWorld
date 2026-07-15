# The Entire World Tech Connector

This project is a local-first AI coding and DCC assistant.

## Core rule

Do not answer project-code questions from assumptions.

When file tools are available, inspect the relevant files first.

If files are large, search for symbols, classes, functions, constants, imports, and call sites before reading targeted sections.

If files cannot be inspected, say so and stop.

---

# Tool-use rules

Only use tools that are actually exposed by Continue.

Never invent tool names.

Do not use assumed tools such as:

- `cat_file`
- `update_file`
- `list_files`
- `edit_existing_file`

unless Continue explicitly exposes them.

Preferred Continue tools:

- `read_file`
- `read_file_range`
- `grep_search`
- `file_glob_search`
- `ls`

When unsure which tools are available, inspect the available tool list instead of guessing.

---

# Project index usage

If a project index, symbol index, AST index, embedding index, knowledge database, or retrieval database already exists, it is the primary source of code discovery.

Do not begin with raw filesystem searching when indexed project knowledge is available.

The investigation order is:

1. Query the project index.
2. Retrieve matching files, symbols, classes, functions, imports, constants, and call sites.
3. Use indexed locations to identify the smallest set of relevant files.
4. Read only the required files or file ranges.
5. Fall back to filesystem search only if:
   - the index is unavailable,
   - the index is stale,
   - the index returns no relevant results,
   - or verification requires checking uncaptured text.

The purpose of indexing is to eliminate unnecessary searching and reduce context size.

Filesystem searching is a fallback, not the default.

---

# Investigation workflow

When investigating code:

1. Query the project index.
2. Identify relevant files and symbols.
3. Read only targeted files.
4. Search for additional callers or references only if needed.
5. Follow imports and call sites before drawing conclusions.
6. Report exactly which files, classes, functions, constants, and symbols were inspected.
7. Clearly distinguish indexed information from verified source code.
8. Clearly mark uncertainty when relevant files could not be inspected.

---

# Search feedback reliability

Whenever reporting progress to the user, describe the actual retrieval strategy being used.

Never generate placeholder or meaningless search feedback.

If investigating systems such as:

- indexing
- knowledge
- retrieval
- search
- embeddings
- context
- routing
- pipelines
- execution
- Unreal
- Maya
- MotionBuilder
- Blender

the investigation should proceed as follows.

## Step 1

Query the project index for:

- symbols
- functions
- classes
- imports
- call sites
- file metadata
- indexed relationships

## Step 2

If necessary, search candidate paths for terms such as:

- index
- indexing
- indexes
- knowledge
- retrieval
- embedding
- search
- vector
- context
- pipeline
- execution

## Step 3

If still necessary, perform targeted content searches for symbols including:

- KnowledgeIndex
- ProjectIndex
- IndexWorker
- initialize_index
- build_index
- load_index
- save_index
- vector_store
- embedding
- semantic_search
- retrieval
- execute
- execute_pipeline

## Step 4

Only if prior steps are insufficient, expand to broader project searching.

Search every project file only when genuinely necessary.

Never conclude something does not exist until:

- the project index has been queried,
- targeted retrieval has been attempted,
- and fallback searching has completed.

---

# Progress reporting

Progress updates should accurately describe what is actually happening.

Good examples:

- Querying the project index for knowledge initialization.
- Retrieving indexed references for execution graph.
- Looking up indexed call sites for ProjectIndex.
- Reading implementation of IndexWorker.
- Following imports from project_intelligence_daemon.py.
- Verifying callers of initialize_index().
- Falling back to filesystem search because the index returned no matches.

Never display messages like:

- Continue tried to search for ""
- Searching...
- Looking around...
- Checking things...
- Thinking...

Feedback should help the user understand what the assistant is actually doing.

---

# Large-file handling

Never read a large file blindly.

Instead:

1. Query the project index.
2. Locate the relevant symbol.
3. Read the smallest useful section.
4. Follow imports.
5. Follow call sites.
6. Summarize incrementally.

Only request a narrower target after retrieval has failed.

---

# Editing workflow

Before making edits:

1. Inspect the target implementation.
2. Inspect related imports.
3. Inspect callers if behavior may change.
4. Inspect related services when architecture may be affected.
5. Propose the smallest safe modification.
6. Edit only the necessary files.
7. Preserve project architecture.
8. Avoid creating duplicate systems when an existing service already performs the task.

---

# Architecture preferences

`main_window.py` should remain a thin orchestration layer.

Move independent functionality into focused modules.

Recommended organization:

- dialogs → `ui/dialogs/`
- widgets → `ui/widgets/`
- workers → `workers/`
- services → `services/`
- DCC integrations → `bridges/` or `services/<dcc>/`
- routing → `router/`
- indexing → `knowledge/`
- retrieval → `knowledge/`
- execution → `execution/`

Prefer symbol-aware retrieval over giant context dumps.

Prefer modular architecture over monolithic files.

---

# Primary goals

I need you to generate the code changes required to support reliable multi-step prompts in the Unreal bridge, with strong awareness of Python function signatures and argument types.

Goal:
A user should be able to give one high-level Unreal request, and the system should plan, gather context, select the correct Unreal Python or custom tool functions, construct valid typed arguments, execute multiple bridge actions, verify each step, and return a final result without needing a separate prompt for every action.

Before writing code, inspect the current Unreal bridge, Unreal tools, intent parser, capability registry, selected context, chat runtime, project index, function registry, execution/rewrite services, and any code that exposes Python functions to the assistant.

Implement the smallest reliable version of this.

Required behavior:

1. Index available callable Python functions from:
   - Unreal Python API wrappers
   - custom Unreal tools
   - bridge-exposed functions
   - project tool modules

2. For each callable, capture:
   - function name
   - module path
   - docstring
   - parameter names
   - parameter type annotations
   - default values
   - return annotation
   - whether the function is safe to execute
   - whether it reads data, modifies assets, modifies the level, or saves files
   - example usage when available

3. Expose this callable registry to the planner so it can choose tools based on both intent and argument compatibility.

4. When planning each step, include:
   - step id
   - natural-language goal
   - selected function or capability
   - required arguments
   - expected argument types
   - source of each argument
   - dependencies on previous steps
   - expected result
   - verification method

5. Add an argument resolver that can turn user language and prior step outputs into valid Python arguments.

The resolver must handle at least:
   - strings
   - ints
   - floats
   - bools
   - lists
   - dicts
   - enums
   - Unreal asset paths
   - Unreal object paths
   - selected actors
   - selected assets
   - Blueprint classes
   - Actor instances
   - Components
   - Transforms
   - Vectors
   - Rotators

6. The resolver should not guess silently. If an argument cannot be resolved confidently, it should:
   - search project/index/selection context first
   - inspect Unreal when needed
   - use safe defaults only when explicitly allowed
   - otherwise stop with a useful missing-argument error

7. Execute the steps in order.

8. Pass typed results from earlier steps into later steps when needed.

9. Verify each step after execution.

10. Stop safely if a step fails.

11. Return a useful error explaining:
   - which step failed
   - what function was selected
   - what arguments were attempted
   - what argument failed resolution
   - what data was missing
   - what the user can do next

12. Return a final summary that includes:
   - executed steps
   - functions called
   - typed arguments used
   - generated or modified assets
   - warnings
   - final verification status

Implementation constraints:

- Do not break existing single-step Unreal prompts.
- Keep the first implementation simple and explicit.
- Prefer deterministic function signature inspection over vague LLM-only tool selection.
- Prefer typed argument resolution over raw string passing.
- Reuse existing bridge, capability registry, project index, selected context, and intent systems where possible.
- Add clear extension points for future planners.
- Add logging so failures can be debugged.
- Do not execute unsafe functions unless they are explicitly registered as safe.
- Do not save assets unless the user requested it or the plan step explicitly requires it.
- Add tests or test stubs for at least:
  - single-step Unreal prompt still works
  - callable registry extracts function signatures
  - planner selects a function based on required argument types
  - string asset path resolves to an Unreal asset
  - selected actor resolves to an Actor argument
  - previous step return value feeds a later step argument
  - failed argument resolution stops the plan safely
  - final response includes function names, typed arguments, and verification information

Example test prompt the system should support:

"Create a new Blueprint Actor named BP_TestMover, add a StaticMeshComponent, assign the cube mesh, place it at the world origin, add a RotatingMovementComponent, save the asset, spawn it in the current level, select it, and confirm it exists."

Expected plan:

1. Create Blueprint Actor BP_TestMover.
2. Add StaticMeshComponent.
3. Resolve cube mesh to a StaticMesh asset.
4. Add StaticMeshComponent with that StaticMesh.
5. Add RotatingMovementComponent.
6. Save Blueprint asset.
7. Spawn actor in current level from the Blueprint class.
8. Select spawned actor.
9. Verify Blueprint asset exists and spawned Actor exists in the level.

Important:
The code should not just generate a text plan. It must generate the supporting implementation for callable discovery, typed argument resolution, multi-step execution, and verification.

# Model usage

Fast edits:

- Qwen 2.5 Coder 7B

Autocomplete:

- Qwen 2.5 Coder 1.5B

Architecture / planning / debugging:

- Qwen 3
- Devstral
- strongest available local model

Embeddings:

- Nomic Embed

---

# Required behavior for project questions

When asked what a:

- file
- folder
- class
- function
- service
- workflow
- UI panel
- button
- feature
- pipeline
- bridge
- index
- execution system

does:

1. Query the project index.
2. Retrieve indexed symbols and relationships.
3. Read the relevant implementation.
4. Follow imports.
5. Follow callers.
6. Summarize verified behavior.
7. Report exactly which files and symbols were inspected.
8. Explicitly identify any remaining uncertainty.

Never guess.

---

# Required reporting

Reports should distinguish between:

- indexed results
- searched paths
- searched symbols
- inspected files
- inspected classes
- inspected functions
- inspected constants
- verified conclusions
- remaining uncertainty

---

# Additional rules

Do not ask for database paths until searching the project for existing constants, configuration values, or settings.

Do not assume implementation details.

Do not invent project architecture.

Do not invent APIs.

Do not invent tools.

Do not invent symbols.

Do not invent file names.

Do not invent relationships between systems.

do not use terminal commands any more. 

Base conclusions only on inspected code and indexed project information.

If verification cannot be completed because required files or tools are unavailable, explicitly state that instead of guessing.