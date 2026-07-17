# Moving or Renaming a Python Project

Use this workflow when a prompt asks Tech Connector to move a project directory,
rename a Python package, or do both. Treat the request as a package migration,
not a filesystem-only rename.

## Planning Contract

1. Resolve the source, destination, package root, and nearest shared tools root
   from the relevant source file. Do not assume a depot or user-specific path.
2. Inventory first-party imports, dynamic module strings, launch commands,
   persisted paths, generated configs, subprocess working directories, and
   DCC bridge bootstrap paths.
3. Present the destination, package name, compatibility requirements, process
   shutdown needs, validation plan, and destructive cleanup boundary for approval.
4. Update code and configs before moving files. Use one canonical package name
   everywhere to prevent duplicate module identities.
5. Stop owned child processes before moving. MCPHost and DCC bridge sessions must
   be terminated and reaped when they are no longer needed.
6. Prefer an atomic directory move. If a live workspace watcher locks the root,
   copy to the destination, hash-verify every non-cache file, validate the copied
   package, and only then remove the verified source tree.
7. Regenerate location-bearing config from the new `__file__`, migrate saved user
   settings, and run focused import, syntax, entry-point, bridge, and UI tests.

## Required Checks

- `APP_ROOT` comes from the package's `__file__`.
- `TOOLS_ROOT` is the nearest ancestor named `tools`, with an optional environment
  override only when the application explicitly supports one.
- Internal imports use the canonical package, for example
  `tech_connector.services.settings_service`.
- Entry points add the package parent (`TOOLS_ROOT`) to `sys.path`; library modules
  do not create a second top-level package identity.
- Remote DCC calls use import paths available in the DCC interpreter.
- Saved config, database, cache, and recent-project paths relocate safely.
- The old path is absent from runtime source except explicit compatibility logic.
- Source cleanup never begins until destination hashes and post-move tests pass.

## Tool Operation

Call `tech_connector.services.code_intelligence_service.audit_python_package_layout`
with the project or package root. It returns unqualified first-party imports,
stale absolute paths, intentional legacy compatibility references, parse errors,
and circular top-level import chains. It builds the graph from AST imports that
execute during module initialization; function-local and `TYPE_CHECKING` imports
are deferred and do not count as startup cycles. Planning should treat unqualified
imports, stale paths, parse errors, or circular imports as blockers before approving
source cleanup. Each cycle reports both module names and source paths so the planner
can move shared contracts downward or defer a dependency deliberately.

The audit complements, rather than replaces, focused runtime tests. Process
lifecycle, generated config, DCC importability, and UI launch behavior require
execution checks after relocation.


## Service Cleanup Analysis

Call `analyze_service_cleanup_candidates` from
`tech_connector.services.code_intelligence_service` before consolidating a
service package. It inventories public symbols, imports, inbound callers,
dynamic/test references, related naming groups, oversized modules, ranked
consolidation pairs, existing-subpackage move candidates, dead-code review
candidates, and circular imports.

Treat its output as evidence, not permission to delete. Before removing a dead
candidate, verify external entry points, generated configuration, plugin/DCC
imports, and focused tests. Before combining a pair, build the virtual post-edit
import graph, reject new cycles, parse every changed module, update callers and
patch strings, then run the affected workflows through their normal UI path.
