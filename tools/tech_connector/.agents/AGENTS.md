# The Entire World Tech Connector - Project Coding Guidelines

These rules apply when editing code or suggesting improvements for tools, bridges, and UI components in The Entire World Tech Connector.

## Core Assistant Rules
- **No Assumptions**: Do not answer project-code questions from assumptions. When file tools are available, inspect the relevant files first.
- **Index-First Discovery**: Do not begin with raw filesystem searching when indexed project knowledge is available. Query the project index first to locate matching files/symbols.
- **Progress Reporting**: Progress updates should accurately describe what is actually happening. Avoid generic "Thinking..." or "Searching..." statements; instead, specify the search type, target symbol, or file being processed.
- **No Monoliths**: Keep `main_window.py` as a thin orchestration layer. Move independent functionality into focused modules under `ui/dialogs/`, `ui/widgets/`, `services/`, or `bridges/`.

## General Python Best Practices
- **Type Annotations**: Provide explicit type hints for all public function parameters and return values (e.g., `def my_func(path: str) -> bool:`).
- **Graceful Error Handling**: Wrap DCC calls and OS operations in try-except blocks. Always log or print stack traces using `traceback.print_exc()` on failure.
- **Dynamic Imports**: For dynamic tools or pipelines that might run outside the standard python environment path, prioritize dynamic execution via `importlib.util` instead of static imports.

## PySide6 & PyQt UI Style Rules
- **Thread Safety**: Never write to UI widgets or trigger visual changes directly from background worker threads. Use Qt Signals (`Signal`, `Slot`) to route updates back to the main thread.
- **Dark-Theme Aesthetics**: Match the glassmorphism and green/dark-themed palettes (#161a16 background, #1f5f3a border, #cfcfcf text) for custom widgets and dialogs.
- **Resilient Layouts**: Always add scroll areas (`QScrollArea`) for dynamic dialog listings to avoid content truncation on different monitor DPI settings.

## DCC API Conventions

### Maya Python (`cmds`)
- **Undo Safety**: Wrap scene-modifying actions inside an undo chunk (`cmds.undoInfo(openChunk=True)` / `closeChunk=True`) so operations can be cleanly reversed.
- **Scene Querying**: Check if the scene is saved (`cmds.file(q=True, sceneName=True)`) before performing export operations.

### Unreal Python (`unreal`)
- **Asset Registry**: Query the `AssetRegistry` to locate assets instead of raw directory listing.
- **Thread Safety**: Unreal Python commands must run on the main thread; do not attempt asynchronous calls to the engine API.

### Blender Python (`bpy`)
- **Context Handling**: Be cautious with `bpy.context`. When running operators from background tasks, override the context dict explicitly to avoid poll errors.

### Substance Painter (`substance_painter`)
- **Export Configs**: Ensure textures are exported using explicit export presets to prevent UI lockup. Use `substance_painter.export.export_project_textures`.

### Houdini Python (`hou`)
- **Node Paths**: Always use absolute paths (`/obj/geo1`) when referencing Houdini nodes.

## Prototyping & Experimental Development
When experimenting with new classes, functions, or gameplay systems (especially in Unreal/DCCs) where there is no existing internal code or documentation:
- **Prioritize Internal Codebase**: Always try to build and compose solutions autonomously first, leveraging existing internal functions, classes, utility nodes, and local documentation before looking externally.
- **Restricted Web Search**: Do NOT perform web searches or external tool ingestion unless the user explicitly requests it, or the implementation requires a highly experimental API/technique with zero local codebase footprint. If triggered, ingest reference material (code snippets, forums, docs) to build a clear understanding of the API or technique before writing implementation code.
- **Public Resources Only**: For ethical, legal, and privacy reasons, all external web searches, URL scraping, or git repository ingestions must target ONLY publicly available resources. Never attempt to query private, credential-locked, or paywalled pages/repositories.
- **Isolate in Scratch Files**: Write standalone scripts inside a scratch directory or separate test module to verify the API behavior (e.g., test Unreal Python commands, check Blender context overrides) before modifying the main application layout or production toolsets.
- **Interactive Validation**: Ask the user to run the standalone test or run it through the DCC command routing system to inspect logs/errors before finalizing the implementation plan.
